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
    """
    Отвечает на звонок и записывает 7 секунд аудио в test_record.wav
    """
    caller_number = call.request.headers.get('From', {}).get('number', 'Unknown')
    print(f"\n📞 [SIP] Входящий звонок от: {caller_number}")

    try:
        call.answer()
        print("✅ [SIP] Трубка снята! Говори в телефон (идет запись 7 секунд)...")

        audio_frames = bytearray()
        start_time = time.time()

        # Цикл: читаем звук из линии ровно 7 секунд
        while time.time() - start_time < 7.0:
            # Читаем кусочки аудио.
            # 320 байт = 20 миллисекунд звука (формат PCM, 16-bit, 8000 Hz)
            chunk = call.read_audio(320)
            if chunk:
                audio_frames.extend(chunk)

        print("💾 [SIP] Время вышло, сохраняем звук в файл...")

        # Сохраняем собранные байты в стандартный WAV-файл
        with wave.open("test_record.wav", "wb") as wf:
            wf.setnchannels(1)       # Моно
            wf.setsampwidth(2)       # 16-bit (2 байта на сэмпл)
            wf.setframerate(8000)    # 8000 Hz (стандарт качества SIP)
            wf.writeframes(audio_frames)

        call.hangup()
        print("☎️ [SIP] Звонок завершен. Файл test_record.wav успешно создан!")

    except InvalidStateError as e:
        print(f"⚠️ [SIP] Ошибка состояния звонка: {e}")
    except Exception as e:
        print(f"❌ [SIP] Непредвиденная ошибка: {e}")


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