import os
from fastapi import APIRouter, UploadFile, File, Form, BackgroundTasks
from fastapi.responses import PlainTextResponse
import ai_core
from utils import send_discord_alert

router = APIRouter(prefix="/api/pbx", tags=["Telephony"])


@router.post("/detect-language")
async def pbx_detect_language(audio: UploadFile = File(...)):
	"""
    Asterisk uses this endpoint for quick language detection (first 3 seconds).
    Returns 'RU' or 'LT'.
    """
	audio_bytes = await audio.read()

	if not audio_bytes:
		return PlainTextResponse(content="RU", status_code=200)

	# Run the audio chunk through our new language detector
	lang = await ai_core.detect_language_audio(audio_bytes, "detect.wav", "audio/wav")

	return PlainTextResponse(content=lang, status_code=200)


@router.post("/process-audio")
async def process_pbx_audio(
		background_tasks: BackgroundTasks,
		audio: UploadFile = File(...),
		source_lang: str = Form("ru")
):
	audio_bytes = await audio.read()
	if not audio_bytes:
		return {"status": "error", "message": "Empty"}

	# 1. STT
	raw_text, is_silence = await ai_core.transcribe_audio(audio_bytes, "record.wav", "audio/wav", source_lang)

	# 2. LLM Fix
	if not is_silence:
		translated_text = await ai_core.translate_and_fix(raw_text, source_lang)
	else:
		translated_text = "[Тишина / Шум]"

	# 3. Save Logs securely (creating directory if it doesn't exist)
	records_dir = "/opt/translator/records"
	os.makedirs(records_dir, exist_ok=True)

	with open(os.path.join(records_dir, "test_raw.txt"), "w", encoding="utf-8") as f:
		f.write(raw_text)
	with open(os.path.join(records_dir, "test_translated.txt"), "w", encoding="utf-8") as f:
		f.write(translated_text)

	msg = f"**Raw STT:** {raw_text}\n**LLM Translated:** {translated_text}"
	background_tasks.add_task(send_discord_alert, "📞 Asterisk Translation Log", msg, 3447003)

	return {"status": "success", "raw": raw_text, "translated": translated_text}


# Zadarma Webhook Handler
@router.api_route("/zadarma-webhook", methods=["GET", "POST"])
async def zadarma_webhook_handler():
	return PlainTextResponse(content="OK", status_code=200)