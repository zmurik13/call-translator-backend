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
       # Двуязычная подсказка, чтобы ИИ был готов к обоим языкам
       greetings_prompt = "Sveiki, laba diena, skambinu pagal skelbimą. Здравствуйте, добрый день, звоню по объявлению."

       # УБИРАЕМ language="lt", разрешаем Whisper'у самому думать!
       res = await groq_client.audio.transcriptions.create(
          file=(file_name, audio_bytes, content_type),
          model="whisper-large-v3",
          prompt=greetings_prompt,
          response_format="text"
       )

       text = res.lower().strip('.?!, ')
       print(f"🕵️ [DETECTOR] Whisper услышал текст: '{text}'")

       # Наша великая стена: латиница, кириллические мутанты и словенский бред
       lt_keywords = [
           # Чистый литовский
           "laba", "labas", "sveiki", "rytas", "vakaras", "klausau", "taip", "klausome", "skambinu", "skelbimą", "skelbimo", "skelbima",
           # Если ИИ услышит литовский, но напишет кириллицей (как было с "лаба")
           "лаба", "лабас", "свейки", "ритас", "вакарас", "клаусау",
           # Наши любимые глюки на коротких звуках
           "zvi'et kem", "zveiki", "zdaj", "skenil", "pogovke"
       ]

       if any(word in text for word in lt_keywords):
          print("✅ [DETECTOR] Найдены литовские маркеры -> LT")
          return "LT"

       print("✅ [DETECTOR] Литовских слов нет -> RU (по умолчанию)")
       return "RU"

    except Exception as e:
       print(f"❌ [DETECTOR] Ошибка: {e}")
       return "RU"