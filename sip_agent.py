import os
import time
import wave
import speech_recognition as sr
from dotenv import load_dotenv
from pyVoIP.VoIP import VoIPPhone, InvalidStateError, CallState

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
            if call.state != CallState.ANSWERED:
                print("🛑 [SIP] Собеседник повесил трубку!", flush=True)
                break

            # Берем чистый звук, как в победном test_record_8.wav
            chunk = call.read_audio(320)
            if chunk:
                audio_frames.extend(chunk)

        print("💾 [SIP] Время вышло. Сохраняем WAV...", flush=True)

        if len(audio_frames) > 0:
            wav_path = "/opt/translator/test_record.wav"
            txt_path = "/opt/translator/test_record.txt"

            # 1. СОХРАНЯЕМ ИДЕАЛЬНЫЙ WAV ФАЙЛ
            with wave.open(wav_path, "wb") as wf:
                wf.setnchannels(1)       
                wf.setsampwidth(2)       
                wf.setframerate(8000)    
                wf.writeframes(audio_frames)
            print(f"☎️ [SIP] Файл {wav_path} успешно создан!", flush=True)

            # 2. ЧИТАЕМ ПРЯМО ИЗ ФАЙЛА И РАСПОЗНАЕМ (Самый надежный способ!)
            print("🧠 [STT] Отправляем аудио из файла на распознавание...", flush=True)
            recognizer = sr.Recognizer()
            
            try:
                with sr.AudioFile(wav_path) as source:
                    audio_data = recognizer.record(source)
                
                recognized_text = recognizer.recognize_google(audio_data, language="ru-RU")
                print(f"📝 [STT] Распознано: {recognized_text}", flush=True)
                
                # 3. СОХРАНЯЕМ ТЕКСТ
                with open(txt_path, "w", encoding="utf-8") as f:
                    f.write(recognized_text)
                print(f"✅ [STT] Текст успешно сохранен в {txt_path}!", flush=True)
                
            except sr.UnknownValueError:
                print("⚠️ [STT] Речь не распознана (Google не разобрал слова).", flush=True)
            except sr.RequestError as e:
                print(f"❌ [STT] Ошибка сервиса Google: {e}", flush=True)

        else:
            print("⚠️ [SIP] Аудио не получено (пустой буфер RTP).", flush=True)

        call.hangup()

    except InvalidStateError as e:
        print(f"⚠️ [SIP] Ошибка состояния звонка: {e}", flush=True)
    except Exception as e:
        print(f"❌ [SIP] Непредвиденная ошибка: {e}", flush=True)


def start_sip_client():
    if not all([SIP_SERVER, SIP_USER, SIP_PASSWORD]):
        print("🚨 [FATAL] Не найдены доступы к SIP в файле .env!", flush=True)
        return

    print(f"📡 [SIP] Подключаемся к {SIP_SERVER} как {SIP_USER}...", flush=True)

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
        print("🚀 [SIP] Агент УСПЕШНО запущен и ждет звонков!", flush=True)
        while True:
            time.sleep(1)
    except Exception as e:
        print(f"❌ [SIP] Ошибка подключения: {e}", flush=True)
    finally:
        phone.stop()
        print("🛑 [SIP] Агент остановлен.", flush=True)


if __name__ == "__main__":
    start_sip_client()
