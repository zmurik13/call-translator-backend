from fastapi import APIRouter, UploadFile, File, Form, BackgroundTasks
from fastapi.responses import StreamingResponse, PlainTextResponse
import ai_core
from utils import send_discord_alert

router = APIRouter(prefix="/api/web", tags=["Web Interface"])

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

	# 1. STT
	raw_text, is_silence = await ai_core.transcribe_audio(
		audio_bytes, f"record.{file_ext}", audio.content_type, source_lang
	)

	# 2. LLM (Универсальный переводчик)
	if is_silence:
		silence_map = {"ru": "Извините, я не расслышал.", "lt": "Atsiprašau, neišgirdau.", "pl": "Przepraszam, nie usłyszałem."}
		translated_text = silence_map.get(target_lang, "Silent audio.")
	else:
		translated_text = await ai_core.web_translate_and_fix(raw_text, source_lang, target_lang)

	# 3. Discord
	msg = f"**Route:** {source_lang.upper()} ➔ {target_lang.upper()}\n**Source:** {raw_text}\n**Translated:** {translated_text}\n**Device:** {device_info}"
	background_tasks.add_task(send_discord_alert, "🗣️ Web Translation Log", msg, 3447003)

	# 4. TTS
	audio_stream, success = await ai_core.generate_speech(translated_text, target_lang)

	if not success:
		return PlainTextResponse(content="Error: TTS generation failed.", status_code=500)

	headers = {
		"X-Recognized-Text": raw_text.encode("unicode_escape").decode("utf-8"),
		"X-Translated-Text": translated_text.encode("unicode_escape").decode("utf-8")
	}
	return StreamingResponse(audio_stream, media_type="audio/mpeg", headers=headers)