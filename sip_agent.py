import os
import time
import wave
import audioop
from dotenv import load_dotenv
from pyVoIP.VoIP import VoIPPhone, InvalidStateError, CallState

# Load environment variables
load_dotenv()

SIP_SERVER = os.getenv("ZADARMA_SIP_DOMAIN")
SIP_USER = os.getenv("ZADARMA_SIP_USER")
SIP_PASSWORD = os.getenv("ZADARMA_SIP_PASSWORD")


def answer_call(call):
    caller_number = call.request.headers.get('From', {}).get('number', 'Unknown')
    print(f"\n📞 [SIP] Incoming call from: {caller_number}", flush=True)

    try:
        call.answer()
        
        # Give the SIP RTP channel 0.5 seconds to fully establish audio routing
        time.sleep(0.5)
        
        print("✅ [SIP] Call answered! Speak now (recording for 7 seconds)...", flush=True)

        audio_frames = bytearray()
        start_time = time.time()

        while time.time() - start_time < 7.0:
            if call.state != CallState.ANSWERED:
                print("🛑 [SIP] Caller hung up!", flush=True)
                break

            # Read raw audio chunk provided by pyVoIP
            chunk = call.read_audio(320)
            if chunk:
                audio_frames.extend(chunk)

        print("💾 [SIP] Time is up. Saving test WAV files...", flush=True)

        if len(audio_frames) > 0:
            # 1. Normal 16-bit PCM (Assuming pyVoIP decodes to Little-Endian PCM)
            with wave.open("/opt/translator/test_record_normal.wav", "wb") as wf:
                wf.setnchannels(1)       
                wf.setsampwidth(2)       
                wf.setframerate(8000)    
                wf.writeframes(audio_frames)
                
            # 2. Swapped bytes (in case of Big-Endian mismatch on Linux)
            swapped_frames = audioop.byteswap(bytes(audio_frames), 2)
            with wave.open("/opt/translator/test_record_swapped.wav", "wb") as wf:
                wf.setnchannels(1)       
                wf.setsampwidth(2)       
                wf.setframerate(8000)    
                wf.writeframes(swapped_frames)

            print("☎️ [SIP] Created two files: normal.wav and swapped.wav.", flush=True)
            print("🔍 [DEBUG] STT is temporarily disabled for audio testing.", flush=True)

        else:
            print("⚠️ [SIP] No audio received (RTP buffer empty).", flush=True)

        call.hangup()

    except InvalidStateError as e:
        print(f"⚠️ [SIP] Invalid call state error: {e}", flush=True)
    except Exception as e:
        print(f"❌ [SIP] Unexpected error: {e}", flush=True)


def start_sip_client():
    if not all([SIP_SERVER, SIP_USER, SIP_PASSWORD]):
        print("🚨 [FATAL] SIP credentials not found in .env!", flush=True)
        return

    print(f"📡 [SIP] Connecting to {SIP_SERVER} as {SIP_USER}...", flush=True)

    phone = VoIPPhone(
        SIP_SERVER, 
        5060, 
        SIP_USER, 
        SIP_PASSWORD, 
        myIP="2.24.131.171", 
        callCallback=answer_call
    )

    try:
        phone.start()
        print("🚀 [SIP] Agent successfully started and waiting for calls!", flush=True)
        while True:
            time.sleep(1)
    except Exception as e:
        print(f"❌ [SIP] Connection error: {e}", flush=True)
    finally:
        phone.stop()
        print("🛑 [SIP] Agent stopped.", flush=True)


if __name__ == "__main__":
    start_sip_client()
