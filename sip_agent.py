import os
import time
import wave
from dotenv import load_dotenv
from pyVoIP.VoIP import VoIPPhone, InvalidStateError

# Загружаем переменные из нашего .env файла
load_dotenv()

SIP_SERVER = os.getenv("ZADARMA_SIP_DOMAIN")
SIP_USER = os.getenv("ZADARMA_SIP_USER")
SIP_PASSWORD = os.getenv("ZADARMA_SIP_PASSWORD")


def answer_call(call):
    caller_number = call.request.headers.get('From', {}).get('number', 'Unknown')
    print(f"\n📞 [SIP] Входящий звонок от: {caller_number}", flush=True)

    try:
        call.answer()
        print("✅ [SIP] Трубка снята! Говори в телефон (идет запись 7 секунд)...", flush=True)

        audio_frames = bytearray()
        start_time = time.time()

        while time.time() - start_time < 7.0:
            chunk = call.read_audio(320)
            if chunk:
                audio_frames.extend(chunk)

        print("💾 [SIP] Время вышло, сохраняем звук в файл...", flush=True)

        # ЖЕСТКИЙ АБСОЛЮТНЫЙ ПУТЬ
        with wave.open("/opt/translator/test_record.wav", "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(8000)
            wf.writeframes(audio_frames)

        call.hangup()
        print("☎️ [SIP] Звонок завершен. Файл сохранен!", flush=True)

    except InvalidStateError as e:
        print(f"⚠️ [SIP] Ошибка состояния звонка: {e}", flush=True)
    except Exception as e:
        print(f"❌ [SIP] Непредвиденная ошибка: {e}", flush=True)


def start_sip_client():
	"""
	Инициализация и запуск SIP-телефона.
	"""
	if not all([SIP_SERVER, SIP_USER, SIP_PASSWORD]):
		print("🚨 [FATAL] Не найдены доступы к SIP в файле .env!")
		return

	print(f"📡 [SIP] Подключаемся к {SIP_SERVER} как {SIP_USER}...")

	# Создаем виртуальный телефон
	# Порт 5060 - это стандартный порт для SIP
	phone = VoIPPhone(SIP_SERVER, 5060, SIP_USER, SIP_PASSWORD, callCallback=answer_call)

	try:
		phone.start()
		print("🚀 [SIP] Агент УСПЕШНО запущен и ждет звонков!")

		# Бесконечный цикл, чтобы скрипт не закрылся и продолжал слушать сеть
		while True:
			time.sleep(1)

	except Exception as e:
		print(f"❌ [SIP] Ошибка подключения: {e}")
	finally:
		phone.stop()
		print("🛑 [SIP] Агент остановлен.")


# Этот блок сработает, если запустить скрипт напрямую
if __name__ == "__main__":
	start_sip_client()
