import os
import io
import asyncio
import aiohttp
from dotenv import load_dotenv
from openai import AsyncOpenAI
import edge_tts
import websockets

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
SYSTEM_PROMPT = """You are an elite speech translator (RU <-> LT) for an automotive tire service (RATŲ BAZĖ).
CRITICAL INSTRUCTIONS:
1. FIX STT ERRORS FIRST: The input text comes from speech-to-text and contains severe phonetic errors (e.g., hearing "Lamba sritys" instead of "Labas rytas", or "drūko dangų" instead of "dėl padangų"). You MUST reconstruct the logical original phrase in the source language based on how it sounds, BEFORE translating.
2. CONTEXT VS LITERAL: Use the tire service context to guess misheard words. However, if the user clearly talks about unrelated topics (like food or weather), translate it accurately.
3. Translate the corrected meaning to the OTHER language.
4. Output ONLY the final translated text. No explanations.
5. ANTI-APOLOGY RULE: NEVER apologize. If the input is pure noise, output an empty string."""

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
	"""Идеальные уши от Deepgram Nova-3."""
	try:
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
	print(f"📞 [PBX IN] {source_lang.upper()}: {raw_text}")

	messages = [
		{"role": "system", "content": SYSTEM_PROMPT},
		{"role": "user", "content": f"Source text: {raw_text}"}
	]
	translated = await _call_llm(messages, temperature=0.2)

	print(f"🤖 [PBX OUT] Перевод: {translated}")
	return translated


async def web_translate_and_fix(raw_text, source_lang, target_lang):
	"""Универсальный LLM переводчик для WEB."""
	print(f"🌐 [WEB IN] Маршрут {source_lang.upper()} -> {target_lang.upper()} | Текст: {raw_text}")

	os.environ["no_proxy"] = "*"

	web_system_prompt = f"""You are an elite speech translator.
        CRITICAL INSTRUCTIONS:
        1. FIX STT ERRORS FIRST: The input text comes from speech-to-text and contains severe phonetic errors.
        2. CONTEXT: You work at RATŲ BAZĖ. Use this context to fix garbled audio (e.g., 'padangų').
        3. Translate strictly from {source_lang.upper()} to {target_lang.upper()}. 
        4. PRESERVE GRAMMATICAL PERSON: Never translate third-person statements into first-person.
        5. Output ONLY the final translated text. No explanations. No markdown formatting.
        6. ANTI-APOLOGY RULE: NEVER apologize. If the input is complete gibberish, output an empty string."""

	messages = [
		{"role": "system", "content": web_system_prompt},
		{"role": "user", "content": f"Source text: {raw_text}"}
	]
	translated = await _call_llm(messages, temperature=0.2)

	translated = translated.replace("```", "").replace("`", "").replace('"', '').strip()

	if not translated:
		translated = raw_text

	print(f"✅ [WEB OUT] Перевод: {translated}")
	return translated


async def generate_speech(text, target_lang):
	"""Генерирует MP3 поток через Edge-TTS."""
	if not text or text == "[LLM Error]":
		return None, False

	selected_voice = VOICE_MAP.get(target_lang, "ru-RU-DmitryNeural")
	text = f" , , , {text}"

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


async def _transcribe_lang(session, audio_bytes, lang):
	"""Internal helper to transcribe audio with a strictly enforced language."""
	# Возвращаем nova-3, она лучше работает с тихим телефонным звуком
	url = f"https://api.deepgram.com/v1/listen?model=nova-3&smart_format=true&language={lang}"
	headers = {
		"Authorization": f"Token {DEEPGRAM_API_KEY}",
		"Content-Type": "audio/wav"
	}
	try:
		async with session.post(url, headers=headers, data=audio_bytes) as response:
			res_json = await response.json()
			if "results" in res_json and res_json["results"]["channels"]:
				return res_json["results"]["channels"][0]["alternatives"][0]["transcript"].strip()
	except Exception as e:
		print(f"⚠️ [STT] Request failed for {lang}: {e}")

	return ""


async def detect_language_audio(audio_bytes, file_name, content_type):
	"""Language Detector: Parallel Execution (RU + LT) with LLM Judge."""
	try:
		timeout = aiohttp.ClientTimeout(total=5.0)
		async with aiohttp.ClientSession(timeout=timeout) as session:
			ru_task = _transcribe_lang(session, audio_bytes, "ru")
			lt_task = _transcribe_lang(session, audio_bytes, "lt")

			ru_text, lt_text = await asyncio.gather(ru_task, lt_task)

		print(f"🕵️ [DETECTOR] RU model heard: '{ru_text}'")
		print(f"🕵️ [DETECTOR] LT model heard: '{lt_text}'")

		if not ru_text and not lt_text:
			return "RU", "[Тишина / Шум]"

		# 👇 Усиленный промпт судьи
		classifier_prompt = f"""You are a language judge for a tire service in Lithuania.
We processed an audio snippet using two different speech-to-text models (RU and LT).
- Russian model heard: "{ru_text}"
- Lithuanian model heard: "{lt_text}"

CRITICAL LOGIC:
1. If the RU text is empty but the LT text is gibberish/hallucination (e.g. "Jos juodais po valdytojas", "Otoisteina nuo pabenu"), the user actually spoke Russian but quietly -> Output RU.
2. If the LT text is empty but the RU text is hallucination -> Output LT.
3. If RU is a logical phrase (e.g., "Здравствуйте", "По поводу колес") -> Output RU.
4. If LT is a logical phrase (e.g., "Laba diena", "Skambinu dėl padangų") -> Output LT.
5. Output ONLY TWO LETTERS: LT or RU. Do not explain."""

		messages = [{"role": "user", "content": classifier_prompt}]
		lang_decision = await _call_llm(messages, temperature=0.0)

		if "LT" in lang_decision.upper():
			print(f"✅ [DETECTOR] LLM Judge decided: LT")
			return "LT", lt_text
		else:
			print(f"✅ [DETECTOR] LLM Judge decided: RU")
			return "RU", ru_text

	except asyncio.TimeoutError:
		print("❌ [DETECTOR] Deepgram Timeout (5s)!")
		return "RU", ""
	except Exception as e:
		print(f"❌ [DETECTOR] Error: {e}")
		return "RU", ""
