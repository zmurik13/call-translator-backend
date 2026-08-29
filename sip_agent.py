import os
import time
import wave
import audioop
import speech_recognition as sr
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

            chunk = call.read_audio(320)
            if chunk:
                # ВОТ ОНО! Меняем alaw2lin на ulaw2lin (распаковываем американский кодек)
                pcm_chunk = audioop.ulaw2lin(chunk, 2)
                audio_frames.extend(pcm_chunk)

        print("💾 [SIP] Time is up. Saving WAV...", flush=True)

        if len(audio_frames) > 0:
            wav_path = "/opt/translator/test_record.wav"
            txt_path = "/opt/translator/test_record.txt"

            # 1. Save pure PCM WAV file
            with wave.open(wav_path, "wb") as wf:
                wf.setnchannels(1)       
                wf.setsampwidth(2)       
                wf.setframerate(8000)    
                wf.writeframes(audio_frames)
            print(f"☎️ [SIP] File {wav_path} successfully created!", flush=True)

            # 2. Read from WAV and run STT
            print("🧠 [STT] Sending audio for transcription...", flush=True)
            recognizer = sr.Recognizer()
            
            try:
                with sr.AudioFile(wav_path) as source:
                    # Calibrate noise floor
                    recognizer.adjust_for_ambient_noise(source, duration=0.5)
                    audio_data = recognizer.record(source)
                
                # Recognize text
                recognized_text = recognizer.recognize_google(audio_data, language="ru-RU")
                print(f"📝 [STT] Recognized: {recognized_text}", flush=True)
                
                # 3. Save text
                with open(txt_path, "w", encoding="utf-8") as f:
                    f.write(recognized_text)
                print(f"✅ [STT] Text successfully saved to {txt_path}!", flush=True)
                
            except sr.UnknownValueError:
                print("⚠️ [STT] Speech not recognized (no words detected or too noisy).", flush=True)
            except sr.RequestError as e:
                print(f"❌ [STT] Google API error: {e}", flush=True)

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
