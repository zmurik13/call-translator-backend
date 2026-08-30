import os
import time
import wave
import threading
import httpx
from dotenv import load_dotenv
from pyVoIP.VoIP import VoIPPhone, InvalidStateError

# Load environment variables
load_dotenv()

SIP_SERVER = os.getenv("ZADARMA_SIP_DOMAIN")
SIP_USER = os.getenv("ZADARMA_SIP_USER")
SIP_PASSWORD = os.getenv("ZADARMA_SIP_PASSWORD")


def send_to_api():
	"""
	Sends the recorded WAV file to the local FastAPI backend.
	"""
	api_url = "http://127.0.0.1:8000/api/pbx/process-audio"
	file_path = "/opt/translator/records/record.wav"

	print("🚀 [SIP] Sending audio to translation API...")
	try:
		with open(file_path, "rb") as f:
			files = {'audio': ('record.wav', f, 'audio/wav')}
			data = {'source_lang': 'ru'}

			# Using httpx synchronous client to send multipart form data
			response = httpx.post(api_url, files=files, data=data, timeout=30.0)

			print(f"✅ [SIP] API Response: {response.text}")
	except Exception as e:
		print(f"❌ [SIP] Failed to send audio to API: {e}")


def answer_call(call):
	"""
	Answers the call, records 7 seconds of audio, saves it, and triggers API request.
	"""
	caller_number = call.request.headers.get('From', {}).get('number', 'Unknown')
	print(f"\n📞 [SIP] Incoming call from: {caller_number}")

	try:
		call.answer()
		print("✅ [SIP] Call answered! Recording 7 seconds...")

		audio_frames = bytearray()
		start_time = time.time()

		# Read audio stream for exactly 7 seconds
		while time.time() - start_time < 7.0:
			chunk = call.read_audio(320)
			if chunk:
				audio_frames.extend(chunk)

		print("💾 [SIP] Time is up, saving audio to file...")

		file_path = "/opt/translator/records/record.wav"

		with wave.open(file_path, "wb") as wf:
			wf.setnchannels(1)  # Mono
			wf.setsampwidth(2)  # 16-bit
			wf.setframerate(8000)  # 8000 Hz (Standard SIP quality)
			wf.writeframes(audio_frames)

		call.hangup()
		print(f"☎️ [SIP] Call finished. File {file_path} created successfully!")

		# Run API request in a separate thread to avoid blocking the VoIP SIP loop
		threading.Thread(target=send_to_api, daemon=True).start()

	except InvalidStateError as e:
		print(f"⚠️ [SIP] Call state error: {e}")
	except Exception as e:
		print(f"❌ [SIP] Unexpected error during call: {e}")


def start_sip_client():
	"""
	Initializes and starts the SIP VoIP Phone client.
	"""
	if not all([SIP_SERVER, SIP_USER, SIP_PASSWORD]):
		print("🚨 [FATAL] Missing SIP credentials in .env file!")
		return

	print(f"📡 [SIP] Connecting to {SIP_SERVER} as {SIP_USER}...")

	# Initialize pyVoIP phone instance
	phone = VoIPPhone(SIP_SERVER, 5060, SIP_USER, SIP_PASSWORD, callCallback=answer_call)

	try:
		phone.start()
		print("🚀 [SIP] Agent SUCCESSFULLY started and waiting for calls!")

		# Keep thread alive
		while True:
			time.sleep(1)

	except Exception as e:
		print(f"❌ [SIP] Connection error: {e}")
	finally:
		phone.stop()
		print("🛑 [SIP] Agent stopped.")


if __name__ == "__main__":
	start_sip_client()