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
SYSTEM_PROMPT = """You are an elite, ultra-fast speech translator (RU <-> LT) for an automotive tire service (RATŲ BAZĖ).
CRITICAL INSTRUCTIONS:
1. TRANSLATE EVERYTHING LITERALLY: Even if the user talks about food, weather, or unrelated topics, translate it accurately. Do not force the tire context if the words mean something else.
2. CONTEXTUAL RECONSTRUCTION: Input might come from noisy phone lines. Reconstruct the logical phrase before translating.
3. Translate the corrected meaning to the OTHER language (If input is Russian -> Lithuanian. If input is Lithuanian -> Russian).
4. GRAMMAR STRICTNESS: Ensure absolute grammatical perfection.
5. Output ONLY the final translated text. No explanations.
6. ANTI-APOLOGY RULE: NEVER apologize or say "I cannot help". If the input is complete gibberish or noise, output an empty string."""

VOICE_MAP = {
	"lt": "lt-LT-LeonasNeural",
	"ru": "ru-RU-DmitryNeural",
	"pl": "pl-PL-MarekNeural"
}

# Оставили только жесткие галлюцинации. Короткие слова теперь разрешены.
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
		content = res.choices[0].message.content
		return content.strip() if content else ""
	except Exception as e:
		print(f"⚠️ [LLM] gpt-4o-mini не ответил ({e}). Переключаюсь на Gemini Flash...")
		try:
			res = await or_client.chat.completions.create(
				model="google/gemini-flash-1.5",
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
	"""Идеальные уши от Deepgram Nova-3. Сверхчувствительный режим (ловит короткие слова)."""
	try:
		# dictation=true и filler_words=true запрещают Deepgram игнорировать короткие звуки
		url = f"https://api.deepgram.com/v1/listen?model=nova-3&smart_format=true&language={source_lang}&dictation=true&filler_words=true"
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

				# Блокируем только откровенные галлюцинации и полную тишину
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
1. You work at RATŲ BAZĖ, but YOU MUST TRANSLATE EVERYTHING LITERALLY, even if the user talks about food, weather, or unrelated topics. Do not force the tire context if the words mean something else.
2. Translate strictly from {source_lang.upper()} to {target_lang.upper()}. Beware of false friends (e.g., LT 'man' means 'to me', not 'adult male').
3. Output ONLY the final translated text. No explanations.
4. ANTI-APOLOGY RULE: NEVER apologize. If the input is complete gibberish, output an empty string."""

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
	"""Детектор языка: Deepgram (Литовский режим/Транслит) + GPT-4o-mini."""
	try:
		# УБРАЛИ detect_language=true! ЖЕСТКО ставим language=lt.
		# Пусть пишет русский транслитом, LLM сама разберется, и никаких испанских галлюцинаций.
		url = "https://api.deepgram.com/v1/listen?model=nova-3&smart_format=true&language=lt"
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
- The text might be Lithuanian OR Russian written in Latin letters (e.g., 'zdrastvuite').
- If it sounds like Lithuanian phonetics or has clear Lithuanian context, return 'LT'.
- If it is Russian (even if transliterated), return 'RU'.
- Output ONLY TWO LETTERS: LT or RU. Do not explain anything."""

		messages = [{"role": "user", "content": classifier_prompt}]
		lang_decision = await _call_llm(messages, temperature=0.0)

		if "LT" in lang_decision.upper():
			print(f"✅ [DETECTOR] LLM постановила: LT (Анализ текста: {raw_text})")
			return "LT", raw_text
		else:
			print(f"✅ [DETECTOR] LLM постановила: RU (Анализ текста: {raw_text})")
			return "RU", raw_text

	except Exception as e:
		print(f"❌ [DETECTOR] Ошибка: {e}")
		return "RU", ""