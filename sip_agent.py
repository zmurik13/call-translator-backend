import os
import speech_recognition as sr
from fastapi import FastAPI
import uvicorn

app = FastAPI()

@app.post("/api/recognize")
async def recognize_audio():
    wav_path = "/opt/translator/test_record.wav"
    txt_path = "/opt/translator/test_record.txt"

    print("\n🧠 [AI] Сигнал от Asterisk получен! Начинаем распознавание...", flush=True)
    
    if not os.path.exists(wav_path):
        print(f"❌ [AI] Ошибка: Файл {wav_path} не найден!", flush=True)
        return {"status": "error", "message": "File not found"}

    recognizer = sr.Recognizer()
    try:
        # Читаем идеально чистый звук, записанный Астериском
        with sr.AudioFile(wav_path) as source:
            audio_data = recognizer.record(source)
            
        text = recognizer.recognize_google(audio_data, language="ru-RU")
        print(f"📝 [STT] Распознано: {text}", flush=True)
        
        # Сохраняем результат
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(text)
            
        return {"status": "success", "text": text}
        
    except sr.UnknownValueError:
        print("⚠️ [STT] Речь не распознана (тишина или неразборчиво).", flush=True)
        return {"status": "error", "message": "Speech not recognized"}
    except Exception as e:
        print(f"❌ [STT] API Ошибка: {e}", flush=True)
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
