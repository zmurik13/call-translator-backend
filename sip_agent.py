import os
import time
from dotenv import load_dotenv
from pyVoIP.VoIP import VoIPPhone, InvalidStateError

# Загружаем переменные из нашего .env файла
load_dotenv()

SIP_SERVER = os.getenv("ZADARMA_SIP_DOMAIN")
SIP_USER = os.getenv("ZADARMA_SIP_USER")
SIP_PASSWORD = os.getenv("ZADARMA_SIP_PASSWORD")


def answer_call(call):
	"""
	Эта функция автоматически вызывается библиотекой pyVoIP,
	когда на наш номер поступает входящий звонок.
	"""
	caller_number = call.request.headers.get('From', {}).get('number', 'Unknown')
	print(f"\n📞 [SIP] Входящий звонок от: {caller_number}")

	try:
		# Снимаем трубку
		call.answer()
		print("✅ [SIP] Трубка снята!")

		# Здесь в будущем мы будем передавать звук из Groq/Edge-TTS.
		# А пока просто "молчим" в трубку 5 секунд.
		print("⏳ [SIP] Держим линию 5 секунд...")
		time.sleep(5)

		# Кладем трубку
		call.hangup()
		print("☎️ [SIP] Звонок успешно завершен.")

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