import json
import asyncio
from fastapi import APIRouter, UploadFile, File, Form, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse, PlainTextResponse
import ai_core
from utils import send_discord_alert

router = APIRouter(prefix="/api/web", tags=["Web Interface"])

# === СТАРЫЙ РЕЖИМ РАЦИИ (Оставляем как резерв для старых телефонов) ===
@router.post("/translate-voice")
async def process_voice_translation(
       background_tasks: BackgroundTasks,
       audio: UploadFile = File(...),
       source_lang: str = Form(...),
       target_lang: str = Form(...),
       device_info: str = Form("Unknown Device")
):
    audio_bytes = await audio.read()
    if not audio_bytes:
       return PlainTextResponse(content="Error: Audio file is empty.", status_code=400)

    file_ext = "mp4" if "mp4" in audio.content_type or "m4a" in audio.filename else "webm"
    raw_text, is_silence = await ai_core.transcribe_audio(
        audio_bytes, f"record.{file_ext}", audio.content_type, source_lang
    )

    if is_silence:
       silence_map = {"ru": "Извините, я не расслышал.", "lt": "Atsiprašau, neišgirdau.", "pl": "Przepraszam, nie usłyszałem."}
       translated_text = silence_map.get(target_lang, "Silent audio.")
    else:
       translated_text = await ai_core.web_translate_and_fix(raw_text, source_lang, target_lang)

    msg = f"**Route:** {source_lang.upper()} ➔ {target_lang.upper()}\n**Source:** {raw_text}\n**Translated:** {translated_text}\n**Device:** {device_info}"
    background_tasks.add_task(send_discord_alert, "🗣️ Web Translation Log", msg, 3447003)

    audio_stream, success = await ai_core.generate_speech(translated_text, target_lang)
    if not success:
       return PlainTextResponse(content="Error: TTS generation failed.", status_code=500)

    headers = {
       "X-Recognized-Text": raw_text.encode("unicode_escape").decode("utf-8"),
       "X-Translated-Text": translated_text.encode("unicode_escape").decode("utf-8")
    }
    return StreamingResponse(audio_stream, media_type="audio/mpeg", headers=headers)


# === ФОНОВЫЙ ВОРКЕР ДЛЯ СТРИМИНГА (Решает проблему пропавших логов и пауз) ===
async def process_translation_pipeline(transcript, source_lang, target_lang, device_info, websocket):
    try:
        translated = await ai_core.web_translate_and_fix(transcript, source_lang, target_lang)
        print(f"🤖 [WS LLM] Перевод: {translated}")

        # 1. ОТПРАВЛЯЕМ ЛОГ В DISCORD СРАЗУ (До звука, чтобы гарантированно зафиксировать)
        msg = (
            f"**Route:** {source_lang.upper()} ➔ {target_lang.upper()}\n"
            f"**Source:** {transcript}\n"
            f"**Translated:** {translated}\n"
            f"{device_info}"
        )
        asyncio.create_task(send_discord_alert("🗣️ Web Stream Log", msg, 3447003))

        # 2. Отправляем текст перевода в браузер
        try:
            await websocket.send_text(json.dumps({"type": "llm", "text": translated}))
        except Exception:
            print("⚠️ [WS] Клиент уже отключился (текст не доставлен)")
            return # Если связи нет, звук генерировать бессмысленно

        # 3. Генерируем звук и отправляем клиенту
        audio_stream, success = await ai_core.generate_speech(translated, target_lang)
        if success:
            try:
                await websocket.send_bytes(audio_stream.read())
                await websocket.send_text(json.dumps({"type": "audio_done"}))
            except Exception:
                print("⚠️ [WS] Клиент отключился до получения аудиофайла")
    except Exception as e:
        print(f"❌ Ошибка в пайплайне перевода: {e}")


# === НОВЫЙ РЕЖИМ СТРИМИНГА (Потоковый перевод) ===
@router.websocket("/ws/translate")
async def websocket_translate(websocket: WebSocket):
    await websocket.accept()
    print("🟢 [WS] Клиент подключился для стриминга")
    dg_socket = None

    try:
       # 1. Ждем настройки
       init_data = await websocket.receive_text()
       config = json.loads(init_data)
       source_lang = config.get("source_lang", "ru")
       target_lang = config.get("target_lang", "lt")
       device_info = config.get("device_info", "📱 Устройство неизвестно")

       print(f"⚙️ [WS] Настройки получены: {source_lang.upper()} ➔ {target_lang.upper()}")

       # 2. Подключение к Deepgram
       dg_socket = await ai_core.connect_deepgram_live(source_lang)
       if not dg_socket:
          raise Exception("Не удалось создать сокет Deepgram")

       # 3. Чтение звука/команд
       async def receive_from_client():
          try:
             while True:
                message = await websocket.receive()

                if "bytes" in message:
                   await dg_socket.send(message["bytes"])
                elif "text" in message:
                   try:
                      data = json.loads(message["text"])
                      if data.get("type") == "stop_audio":
                         print("🛑 [WS] Кнопка отпущена. Вытягиваем остатки аудио...")
                         await dg_socket.send(json.dumps({"type": "CloseStream"}))
                   except:
                      pass
          except WebSocketDisconnect:
             pass
          except Exception as e:
             print(f"⚠️ [WS] Ошибка чтения от клиента: {e}")

       # 4. Прослушивание Deepgram
       async def process_deepgram():
          try:
             async for message in dg_socket:
                res = json.loads(message)
                if "channel" in res:
                   transcript = res["channel"]["alternatives"][0]["transcript"]
                   is_final = res.get("is_final", False)

                   if transcript and is_final:
                      print(f"🗣️ [WS STT] Распознано: {transcript}")
                      await websocket.send_text(json.dumps({"type": "stt", "text": transcript}))

                      # 🔥 Передаем задачу в фоне, чтобы цикл продолжил слушать микрофон
                      asyncio.create_task(
                          process_translation_pipeline(transcript, source_lang, target_lang, device_info, websocket)
                      )
          except Exception as e:
             print(f"⚠️ [WS] Ошибка обработки Deepgram: {e}")

       # 5. Запуск
       client_task = asyncio.create_task(receive_from_client())
       dg_task = asyncio.create_task(process_deepgram())

       done, pending = await asyncio.wait(
          [client_task, dg_task], return_when=asyncio.FIRST_COMPLETED
       )
       for task in pending:
          task.cancel()

    except WebSocketDisconnect:
       print("🔴 [WS] Соединение закрыто браузером")
    except Exception as e:
       print(f"❌ [WS] Критическая ошибка: {e}")
    finally:
       if dg_socket:
          try:
             await dg_socket.close()
          except:
             pass