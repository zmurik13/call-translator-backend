import os
import io
import asyncio
from groq import AsyncGroq
import edge_tts

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
groq_client = AsyncGroq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

SYSTEM_PROMPT = """You are an elite, ultra-fast speech translator (RU <-> LT).
CRITICAL INSTRUCTIONS:
1. CONTEXTUAL RECONSTRUCTION: Input might come from noisy phone lines or web mics. Expect phonetic hallucinations (e.g., 'выжимают' instead of 'вызываю'). Reconstruct the logical intended phrase based on context before translating.
2. Translate the corrected meaning to the OTHER language (If input is Russian -> Lithuanian. If input is Lithuanian -> Russian).
3. GRAMMAR STRICTNESS: Ensure absolute grammatical perfection and natural phrasing.
4. PUNCTUATION FOR TTS: Apply flawless punctuation (periods, commas, question marks).
5. Output ONLY the final translated text. No explanations, no quotes."""

PROMPT_RU = "Привет! Проверка связи. Рату базе, шиномонтаж. Вызываю один два три. Доброе утро."
PROMPT_LT = "Labas rytas. Ratų bazė. Padangų montavimas. Patikrinam ryšį. Ačiū."

VOICE_MAP = {"lt": "lt-LT-LeonasNeural", "ru": "ru-RU-DmitryNeural"}
HALLUCINATIONS = ["продолжение следует", "подписывайтесь на канал", "to be continued", "amara.org",
                  "спасибо за просмотр", "dėkis"]


async def transcribe_audio(audio_bytes, file_name, content_type, source_lang):
	"""Распознает звук от любого источника (Web/PBX)."""
	current_prompt = PROMPT_RU if source_lang == "ru" else PROMPT_LT
	try:
		res = await groq_client.audio.transcriptions.create(
			file=(file_name, audio_bytes, content_type),
			model="whisper-large-v3",
			prompt=current_prompt,
			language=source_lang,
			response_format="text"
		)
		text = res.strip()
		lower_text = text.lower().strip('.?!, ')

		if not lower_text or any(h in lower_text for h in HALLUCINATIONS) or lower_text in ["ačiū", "спасибо", "привет",
		                                                                                    "labas"]:
			return "[Тишина / Шум]", True

		return text, False
	except Exception as e:
		print(f"STT Error: {e}")
		return "[STT Error]", True


async def translate_and_fix(raw_text, source_lang):
	"""LLM исправляет ошибки и переводит."""
	try:
		res = await groq_client.chat.completions.create(
			model="openai/gpt-oss-120b",
			messages=[
				{"role": "system", "content": SYSTEM_PROMPT},
				{"role": "user", "content": f"Source text: {raw_text}"}
			],
			temperature=0.2
		)
		return res.choices[0].message.content.strip()
	except Exception as e:
		print(f"LLM Error: {e}")
		return "[LLM Error]"


async def generate_speech(text, target_lang):
	"""Генерирует MP3 поток через Edge-TTS."""
	selected_voice = VOICE_MAP[target_lang]
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
			print(f"TTS Error attempt {attempt + 1}: {e}")
			await asyncio.sleep(0.5)

	return None, False


async def detect_language_audio(audio_bytes, file_name, content_type):
	"""Определяет язык по транскрипции текста (поиск ключевых слов)."""
	try:
		# МАКСИМАЛЬНЫЙ КОНТЕКСТ ДЛЯ ИИ (Приветствия + Типичные фразы автосервиса)
		greetings_prompt = (
			"Taip, klausau. Labas rytas, laba diena, labas vakaras. "
			"Sveiki, skambinu dėl padangų, ratų bazė. Noriu paklausti, kiek kainuoja, "
			"ar turite laisvo laiko, noriu užsiregistruoti, pakeisti."
		)

		res = await groq_client.audio.transcriptions.create(
			file=(file_name, audio_bytes, content_type),
			model="whisper-large-v3",
			prompt=greetings_prompt,
			temperature=0.0,
			response_format="text"
		)

		text = res.lower().strip('.?!, ')
		print(f"🕵️ [DETECTOR] Whisper услышал текст: '{text}'")

		# РАСШИРЕННЫЙ СЛОВАРЬ (Только 100% литовские корни)
		lt_keywords = [
			# Приветствия
			"laba", "labas", "sveiki", "rytas", "vakaras", "diena", "klausau", "taip", "klausome",

			# Действия и вопросы клиента
			"skambinu", "skambin", "skelbimą", "skelbimo", "skelbima",
			"noriu", "paklausti", "užsiregistruoti", "registruotis",
			"kainuoja", "kaina", "laiko", "laikas", "kada",

			# Автомобильная тематика RATŲ BAZĖ
			"padangų", "padangas", "padangu", "ratų", "ratu", "baze",
			"keitimas", "pakeisti", "montavimas", "tepalai", "tepalų", "stabdžių",

			# Наши любимые транслитерации
			"лаба", "лабас", "свейки", "ритас", "вакарас", "клаусау",
			"скамбиню", "скамбин", "падангу", "секи", "дэл",

			# Золотой фонд галлюцинаций
			"zvi'et kem", "zveiki", "zdaj", "skenil", "pogovke", "звуки", "благослови", "каменью", "подуньгу",
			"vamos a ver", "vamos"
		]

		if any(word in text for word in lt_keywords):
			print("✅ [DETECTOR] Найдены литовские маркеры -> LT")
			return "LT"

		print("✅ [DETECTOR] Литовских слов нет -> RU (по умолчанию)")
		return "RU"

	except Exception as e:
		print(f"❌ [DETECTOR] Ошибка: {e}")
		return "RU"