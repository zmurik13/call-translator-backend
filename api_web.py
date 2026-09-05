import json
import asyncio
from fastapi import APIRouter, UploadFile, File, Form, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse, PlainTextResponse
import ai_core
from utils import send_discord_alert

router = APIRouter(prefix="/api/web", tags=["Web Interface"])


# === СТАРЫЙ РЕЖИМ РАЦИИ (Оставляем как резерв) ===
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
	raw_text, is_silence = await ai_core.transcribe_audio(audio_bytes, f"record.{file_ext}", audio.content_type,
	                                                      source_lang)

	if is_silence:
		silence_map = {"ru": "Извините, я не расслышал.", "lt": "Atsiprašau, neišgirdau.",
		               "pl": "Przepraszam, nie usłyszałem."}
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


# === НОВЫЙ РЕЖИМ СТРИМИНГА (Потоковый перевод) ===
@router.websocket("/ws/translate")
async def websocket_translate(websocket: WebSocket):
	await websocket.accept()
	print("🟢 [WS] Клиент подключился для стриминга")

	try:
		# 1. Ждем первый пакет с настройками от фронтенда (JSON)
		init_data = await websocket.receive_text()
		config = json.loads(init_data)
		source_lang = config.get("source_lang", "ru")
		target_lang = config.get("target_lang", "lt")

		print(f"⚙️ [WS] Настройки получены: {source_lang.upper()} ➔ {target_lang.upper()}")

		# 2. Открываем Live-соединение с Deepgram
		# (Эту функцию мы напишем в ai_core.py на следующем шаге)
		dg_socket = await ai_core.connect_deepgram_live(source_lang)

		# ЗАДАЧА А: Читаем аудио с телефона и льем в Deepgram
		async def receive_from_client():
			try:
				while True:
					audio_chunk = await websocket.receive_bytes()
					await dg_socket.send(audio_chunk)
			except WebSocketDisconnect:
				print("🔴 [WS] Клиент отключился")
			except Exception as e:
				print(f"⚠️ [WS] Ошибка чтения аудио: {e}")

		# ЗАДАЧА Б: Слушаем Deepgram, переводим и шлем результат обратно клиенту
		async def process_deepgram():
			try:
				async for message in dg_socket:
					res = json.loads(message)
					if "channel" in res:
						transcript = res["channel"]["alternatives"][0]["transcript"]
						is_final = res.get("is_final", False)

						# Если фраза завершена и не пустая
						if transcript and is_final:
							print(f"🗣️ [WS STT] Распознано: {transcript}")
							# Шлем текст для обновления UI
							await websocket.send_text(json.dumps({"type": "stt", "text": transcript}))

							# LLM Перевод
							translated = await ai_core.web_translate_and_fix(transcript, source_lang, target_lang)
							print(f"🤖 [WS LLM] Перевод: {translated}")
							await websocket.send_text(json.dumps({"type": "llm", "text": translated}))

							# TTS Озвучка (Шлем бинарный MP3)
							audio_stream, success = await ai_core.generate_speech(translated, target_lang)
							if success:
								await websocket.send_bytes(audio_stream.read())
								await websocket.send_text(json.dumps({"type": "audio_done"}))

							# Алерты в Discord
							msg = f"**[STREAM] Route:** {source_lang.upper()} ➔ {target_lang.upper()}\n**Source:** {transcript}\n**Translated:** {translated}"
							asyncio.create_task(send_discord_alert("⚡ Stream Log", msg, 3066993))
			except Exception as e:
				print(f"⚠️ [WS] Ошибка обработки Deepgram: {e}")

		# Запускаем чтение и запись параллельно!
		client_task = asyncio.create_task(receive_from_client())
		dg_task = asyncio.create_task(process_deepgram())

		# Ждем, пока клиент не закроет сокет
		done, pending = await asyncio.wait(
			[client_task, dg_task], return_when=asyncio.FIRST_COMPLETED
		)
		for task in pending:
			task.cancel()

	except WebSocketDisconnect:
		print("🔴 [WS] Соединение закрыто")
	except Exception as e:
		print(f"❌ [WS] Критическая ошибка: {e}")
	finally:
		# Корректно закрываем сокет Deepgram
		try:
			await dg_socket.close()
		except:
			pass