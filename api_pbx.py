import os
import subprocess
from fastapi import APIRouter, UploadFile, File, Form, BackgroundTasks
from fastapi.responses import PlainTextResponse
import ai_core
from utils import send_discord_alert
from datetime import datetime
import zoneinfo

router = APIRouter(prefix="/api/pbx", tags=["Telephony"])


# === ЗАГЛУШКА ДЛЯ TELEGRAM ===
async def send_telegram_alert(caller_id: str, lang: str, text: str):
	"""
	В будущем здесь будет HTTP-запрос к API Telegram.
	Пока просто выводим красиво в консоль.
	"""
	msg = f"📱 Звонок: {caller_id} | 🌍 Язык: {lang}\n🗣️ Текст: {text}"
	print(f"✈️ [TELEGRAM MOCK] Отправка уведомления:\n{msg}")


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
		return PlainTextResponse(content="RU|error", status_code=200)

	# ===== СОХРАНЯЕМ ФАЙЛ ДЛЯ ОТЛАДКИ =====
	debug_path = "/opt/translator/records/debug_detect.wav"
	with open(debug_path, "wb") as f:
		f.write(audio_bytes)
	print(f"💾 [DEBUG] Аудио сохранено для проверки: {debug_path}")
	# ======================================

	print(f"\n🎧 [DETECT] Звонок от {caller_id}. Аудио для анализа ({len(audio_bytes)} байт)...")

	# Прогоняем через наш детектор (ловим язык и текст)
	lang, transcription = await ai_core.detect_language_audio(audio_bytes, "detect.wav", "audio/wav")

	print(f"✅ [DETECT] Нейросеть приняла решение (Звонок {caller_id}): {lang}")
	print(f"✅ [DETECT] Текст клиента: '{transcription}'")

	# ===== ГЕНЕРАЦИЯ СУФЛЁРА ДЛЯ МАСТЕРА =====
	whisper_text = f"Клиент сказал: {transcription}"
	if lang == "LT":
		whisper_text = f"Литовский язык. Запрос: {transcription}"

	audio_stream, success = await ai_core.generate_speech(whisper_text, "ru")
	whisper_asterisk_path = "error"

	if success:
		mp3_path = f"/tmp/whisper_{caller_id}.mp3"
		wav_path = f"/tmp/whisper_{caller_id}.wav"

		# Сохраняем MP3 от Edge-TTS
		with open(mp3_path, "wb") as f:
			f.write(audio_stream.read())

		# Конвертируем в формат Asterisk (8kHz, 16-bit, mono)
		subprocess.run([
			"ffmpeg", "-y", "-i", mp3_path,
			"-ar", "8000", "-ac", "1", "-acodec", "pcm_s16le", wav_path
		], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

		# Астериску нужен путь БЕЗ расширения .wav для функции Playback/Dial
		whisper_asterisk_path = f"/tmp/whisper_{caller_id}"
	# =========================================

	# ===== SMART DISCORD & TELEGRAM LOGGING =====
	# Кидаем пуш в Телегу
	background_tasks.add_task(send_telegram_alert, caller_id, lang, transcription)

	action_text = "Routing to Manager (SIP 101)" if lang == "RU" else "Starting AI Translator"
	color = 15158332 if lang == "RU" else 3066993  # Red for RU, Green for LT

	# Принудительно ставим таймзону Вильнюса
	tz = zoneinfo.ZoneInfo("Europe/Vilnius")
	current_time = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")

	msg = (
		f"🕒 **Time:** `{current_time}`\n"
		f"📱 **Caller:** `{caller_id}`\n"
		f"🗣️ **Detected Language:** `{lang}`\n"
		f"⚙️ **Action:** {action_text}\n"
		f"📝 **Текст:** *{transcription}*"
	)

	background_tasks.add_task(send_discord_alert, "🔀 Smart Call Routing", msg, color)
	# =======================================

	# Возвращаем Астериску склеенную строку "RU|/tmp/whisper_123"
	response_str = f"{lang}|{whisper_asterisk_path}"
	return PlainTextResponse(content=response_str, status_code=200)


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