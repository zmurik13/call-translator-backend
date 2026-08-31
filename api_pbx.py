import os
from fastapi import APIRouter, UploadFile, File, Form, BackgroundTasks
from fastapi.responses import PlainTextResponse
import ai_core
from utils import send_discord_alert
from fastapi import BackgroundTasks  # Убедись, что BackgroundTasks импортирован!

router = APIRouter(prefix="/api/pbx", tags=["Telephony"])


@router.post("/detect-language")
async def pbx_detect_language(
		background_tasks: BackgroundTasks,
		audio: UploadFile = File(...),
		caller_id: str = Form("Unknown")  # Ловим номер от Астериска
):
	"""
	Asterisk uses this endpoint for quick language detection.
	"""
	audio_bytes = await audio.read()

	if not audio_bytes:
		print(f"⚠️ [DETECT] Ошибка: Получено пустое аудио от {caller_id}!")
		return PlainTextResponse(content="RU", status_code=200)

	# ===== СОХРАНЯЕМ ФАЙЛ ДЛЯ ОТЛАДКИ =====
	debug_path = "/opt/translator/records/debug_detect.wav"
	with open(debug_path, "wb") as f:
		f.write(audio_bytes)
	print(f"💾 [DEBUG] Аудио сохранено для проверки: {debug_path}")
	# ======================================

	print(f"\n🎧 [DETECT] Звонок от {caller_id}. Аудио для анализа ({len(audio_bytes)} байт)...")

	# Прогоняем через наш детектор
	lang = await ai_core.detect_language_audio(audio_bytes, "detect.wav", "audio/wav")

	print(f"✅ [DETECT] Нейросеть приняла решение (Звонок {caller_id}): {lang}")

	# ===== УМНОЕ ЛОГИРОВАНИЕ В DISCORD =====
	action_text = "📞 Проброс звонка на менеджера (SIP 101)" if lang == "RU" else "🤖 Запуск ИИ-переводчика"
	color = 15158332 if lang == "RU" else 3066993  # Красный для RU, Зеленый для LT

	msg = f"**Номер:** `{caller_id}`\n**Услышанный язык:** `{lang}`\n**Действие:** {action_text}"
	background_tasks.add_task(send_discord_alert, "🔀 Smart Call Routing", msg, color)
	# =======================================

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