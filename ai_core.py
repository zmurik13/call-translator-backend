import os
import io
import asyncio
import aiohttp
from dotenv import load_dotenv
from openai import AsyncOpenAI
import edge_tts

# === ЗАГРУЗКА .ENV ===
load_dotenv()

# === API КЛЮЧИ И КЛИЕНТЫ ===
DEEPGRAM_API_KEY = os.environ.get("DEEPGRAM_API_KEY", "")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")

# Мозги (LLM) - Направляем клиента OpenAI в шлюз OpenRouter
or_client = AsyncOpenAI(
	base_url="https://openrouter.ai/api/v1",
	api_key=OPENROUTER_API_KEY,
)

# === КОНСТАНТЫ И ПРОМПТЫ ===
# ДОБАВЛЕНО ПРАВИЛО: НИКАКИХ ИЗВИНЕНИЙ!
SYSTEM_PROMPT = """You are an elite, ultra-fast speech translator (RU <-> LT).
CRITICAL INSTRUCTIONS:
1. CONTEXTUAL RECONSTRUCTION: Input might come from noisy phone lines or web mics. Expect phonetic hallucinations. Reconstruct the logical intended phrase based on context before translating.
2. Translate the corrected meaning to the OTHER language (If input is Russian -> Lithuanian. If input is Lithuanian -> Russian).
3. GRAMMAR STRICTNESS: Ensure absolute grammatical perfection and natural phrasing.
4. PUNCTUATION FOR TTS: Apply flawless punctuation (periods, commas, question marks).
5. Output ONLY the final translated text. No explanations, no quotes.
6. ANTI-APOLOGY RULE: NEVER apologize. NEVER say "I cannot help", "I cannot translate", or "Sorry". If the input is complete gibberish or noise, output an empty string."""

VOICE_MAP = {
	"lt": "lt-LT-LeonasNeural",
	"ru": "ru-RU-DmitryNeural",
	"pl": "pl-PL-MarekNeural"
}

# Мы убрали одиночные слова (спасибо, привет) из галлюцинаций,
# потому что Deepgram слышит их четко и не додумывает лишнего.
HALLUCINATIONS = ["продолжение следует", "подписывайтесь на канал", "to be continued", "amara.org",
                  "спасибо за просмотр"]


# === УМНЫЙ РОУТЕР LLM С ЗАПАСКОЙ ===
async def _call_llm(messages, temperature=0.2):
	"""Вызывает GPT-4o-mini. При любой ошибке бесшовно переключается на Gemini Flash."""
	try:
		res = await or_client.chat.completions.create(
			model="openai/gpt-4o-mini",
			messages=messages,
			temperature=temperature
		)
		# Безопасно получаем контент. Если он None (пустота), возвращаем пустую строку ""
		content = res.choices[0].message.content
		return content.strip() if content else ""

	except Exception as e:
		print(f"⚠️ [LLM] gpt-4o-mini не ответил ({e}). Переключаюсь на Gemini Flash...")
		try:
			res = await or_client.chat.completions.create(
				model="google/gemini-flash-1.5",  # <-- Исправленный ID модели
				messages=messages,
				temperature=temperature
			)
			content = res.choices[0].message.content
			return content.strip() if content else ""

		except Exception as fallback_err:
			print(f"❌ [LLM] Ошибка обоих LLM-моделей: {fallback_err}")
			return "[LLM Error]"


# === ФУНКЦИИ ЯДРА ===

async def transcribe_audio(audio_bytes, file_name, content_type, source_lang):
	"""Идеальные уши от Deepgram Nova-3 (без галлюцинаций Whisper'а)."""
	try:
		# Deepgram ест аудио напрямую через молниеносный REST API
		url = f"https://api.deepgram.com/v1/listen?model=nova-3&smart_format=true&language={source_lang}"
		headers = {
			"Authorization": f"Token {DEEPGRAM_API_KEY}",
			"Content-Type": content_type or "audio/wav"
		}

		async with aiohttp.ClientSession() as session:
			async with session.post(url, headers=headers, data=audio_bytes) as response:
				res_json = await response.json()

				if "results" in res_json and res_json["results"]["channels"]:
					text = res_json["results"]["channels"][0]["alternatives"][0]["transcript"].strip()
				else:
					text = ""

				lower_text = text.lower().strip('.?!, ')

				if not lower_text or any(h in lower_text for h in HALLUCINATIONS):
					return "[Тишина / Шум]", True

				return text, False
	except Exception as e:
		print(f"❌ [STT] Deepgram Error: {e}")
		return "[STT Error]", True


async def translate_and_fix(raw_text, source_lang):
	"""LLM переводчик для PBX."""
	messages = [
		{"role": "system", "content": SYSTEM_PROMPT},
		{"role": "user", "content": f"Source text: {raw_text}"}
	]
	return await _call_llm(messages, temperature=0.2)


async def web_translate_and_fix(raw_text, source_lang, target_lang):
	"""Универсальный LLM переводчик для WEB."""
	web_system_prompt = f"""You are an elite, ultra-fast speech translator.
CRITICAL INSTRUCTIONS:
1. CONTEXT: Automotive service, tire replacement (RATŲ BAZĖ). Expect noisy audio.
2. Translate the text strictly from {source_lang.upper()} to {target_lang.upper()}.
3. GRAMMAR STRICTNESS: Ensure absolute grammatical perfection and natural phrasing.
4. Output ONLY the final translated text. No explanations.
5. ANTI-APOLOGY RULE: NEVER apologize. If the input is complete gibberish, output an empty string."""

	messages = [
		{"role": "system", "content": web_system_prompt},
		{"role": "user", "content": f"Source text: {raw_text}"}
	]
	return await _call_llm(messages, temperature=0.2)


async def generate_speech(text, target_lang):
	"""Генерирует MP3 поток через Edge-TTS (с хаком для паузы)."""
	# Если на вход пришла пустая строка (LLM отсеяла шум), ничего не генерируем
	if not text or text == "[LLM Error]":
		return None, False

	selected_voice = VOICE_MAP.get(target_lang, "ru-RU-DmitryNeural")

	# === ЖЕСТКИЙ ХАК ДЛЯ ПАУЗЫ ===
	text = f". \n\n {text}"

	audio_stream = io.BytesIO()

	for attempt in range(3):
		try:
			tts = edge_tts.Communicate(text, selected_voice)
			async for chunk in tts.stream():
				if chunk["type"] == "audio":
					audio_stream.write(chunk["data"])
			if audio_stream.tell() > 0:
				audio_stream.seek(0)
				return audio_stream, True
		except Exception as e:
			print(f"⚠️ [TTS Error] попытка {attempt + 1}: {e}")
			await asyncio.sleep(0.5)

	return None, False


async def detect_language_audio(audio_bytes, file_name, content_type):
	"""Детектор языка: уши от Deepgram (detect_language=true), мозги от OpenRouter."""
	try:
		# 1. STT: Слушаем через Deepgram с включенным автоопределением языка!
		url = "https://api.deepgram.com/v1/listen?model=nova-3&smart_format=true&detect_language=true"
		headers = {
			"Authorization": f"Token {DEEPGRAM_API_KEY}",
			"Content-Type": content_type or "audio/wav"
		}

		async with aiohttp.ClientSession() as session:
			async with session.post(url, headers=headers, data=audio_bytes) as response:
				res_json = await response.json()
				if "results" in res_json and res_json["results"]["channels"]:
					raw_text = res_json["results"]["channels"][0]["alternatives"][0]["transcript"].strip()
				else:
					raw_text = ""

		print(f"🕵️ [DETECTOR] Deepgram услышал текст: '{raw_text}'")

		if not raw_text:
			return "RU", "[Тишина / Шум]"

		# 2. LLM MAGIC: Классифицируем
		classifier_prompt = f"""You are a language detection router for an auto service in Lithuania.
Analyze the following transcription: "{raw_text}"

Instructions:
- The text might contain phonetic hallucinations, weird translations, or Cyrillic transliterations.
- If it sounds like Lithuanian phonetics or has clear Lithuanian context, return 'LT'.
- Otherwise, return 'RU'.
- Output ONLY TWO LETTERS: LT or RU. Do not explain anything."""

		messages = [{"role": "user", "content": classifier_prompt}]
		lang_decision = await _call_llm(messages, temperature=0.0)
		lang_decision = lang_decision.upper()

		if "LT" in lang_decision:
			print(f"✅ [DETECTOR] LLM постановила: LT (Анализ текста: {raw_text})")
			return "LT", raw_text
		else:
			print(f"✅ [DETECTOR] LLM постановила: RU (Анализ текста: {raw_text})")
			return "RU", raw_text

	except Exception as e:
		print(f"❌ [DETECTOR] Ошибка: {e}")
		return "RU", ""