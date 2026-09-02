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
PROMPT_PL = "Dzień dobry. Serwis opon, wymiana kół. Słucham, dziękuję. Ile to kosztuje?"

VOICE_MAP = {
    "lt": "lt-LT-LeonasNeural",
    "ru": "ru-RU-DmitryNeural",
    "pl": "pl-PL-MarekNeural"
}

HALLUCINATIONS = ["продолжение следует", "подписывайтесь на канал", "to be continued", "amara.org",
                  "спасибо за просмотр", "dėkis"]


async def transcribe_audio(audio_bytes, file_name, content_type, source_lang):
    """Распознает звук от любого источника (Web/PBX)."""
    prompts = {"ru": PROMPT_RU, "lt": PROMPT_LT, "pl": PROMPT_PL}
    current_prompt = prompts.get(source_lang, PROMPT_RU)

    try:
       res = await groq_client.audio.transcriptions.create(
          file=(file_name, audio_bytes, content_type),
          model="whisper-large-v3-turbo",  # <--- ВКЛЮЧИЛИ TURBO-РЕЖИМ
          prompt=current_prompt,
          language=source_lang,
          response_format="text"
       )
       text = res.strip()
       lower_text = text.lower().strip('.?!, ')

       if not lower_text or any(h in lower_text for h in HALLUCINATIONS) or lower_text in ["ačiū", "спасибо", "привет",
                                                                                           "labas", "dzięki"]:
          return "[Тишина / Шум]", True

       return text, False
    except Exception as e:
       print(f"STT Error: {e}")
       return "[STT Error]", True


async def translate_and_fix(raw_text, source_lang):
    """LLM исправляет ошибки и переводит (Только для PBX)."""
    try:
       res = await groq_client.chat.completions.create(
          model="llama-3.3-70b-versatile",  # <--- СТАБИЛЬНЫЙ ПРОДАКШН-ФЛАГМАН
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


async def web_translate_and_fix(raw_text, source_lang, target_lang):
    """Универсальный LLM переводчик для WEB-интерфейса (Любые пары)."""
    web_system_prompt = f"""You are an elite, ultra-fast speech translator.
CRITICAL INSTRUCTIONS:
1. CONTEXT: Automotive service, tire replacement (RATŲ BAZĖ). Expect noisy audio.
2. Translate the text strictly from {source_lang.upper()} to {target_lang.upper()}.
3. GRAMMAR STRICTNESS: Ensure absolute grammatical perfection and natural phrasing.
4. Output ONLY the final translated text. No explanations."""

    try:
       res = await groq_client.chat.completions.create(
          model="llama-3.3-70b-versatile",  # <--- СТАБИЛЬНЫЙ ПРОДАКШН-ФЛАГМАН
          messages=[
             {"role": "system", "content": web_system_prompt},
             {"role": "user", "content": f"Source text: {raw_text}"}
          ],
          temperature=0.2
       )
       return res.choices[0].message.content.strip()
    except Exception as e:
       print(f"WEB LLM Error: {e}")
       return "[LLM Error]"


async def generate_speech(text, target_lang):
    """Генерирует MP3 поток через Edge-TTS."""
    selected_voice = VOICE_MAP.get(target_lang, "ru-RU-DmitryNeural")

    # === ЖЕСТКИЙ ХАК ДЛЯ ПАУЗЫ ===
    # Точка и двойной абзац заставляют нейросеть сделать "вдох" перед чтением текста.
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
          print(f"TTS Error attempt {attempt + 1}: {e}")
          await asyncio.sleep(0.5)

    return None, False


async def detect_language_audio(audio_bytes, file_name, content_type):
    """Определяет язык с помощью транскрипции Whisper и умного LLM-классификатора."""
    try:
       greetings_prompt = (
          "Taip, klausau. Labas rytas, laba diena, labas vakaras. "
          "Sveiki, skambinu dėl padangų, ratų bazė. Noriu paklausti, kiek kainuoja, "
          "ar turite laisvo laiko, noriu užsiregistruoti, pakeisti."
       )

       res = await groq_client.audio.transcriptions.create(
          file=(file_name, audio_bytes, content_type),
          model="whisper-large-v3-turbo",  # <--- ВКЛЮЧИЛИ TURBO-РЕЖИМ
          prompt=greetings_prompt,
          temperature=0.0,
          response_format="text"
       )

       raw_text = res.strip()
       print(f"🕵️ [DETECTOR] Whisper услышал текст: '{raw_text}'")

       if not raw_text:
          return "RU", "[Тишина / Шум]"

       classifier_prompt = f"""You are a language detection router for an auto service in Lithuania.
Analyze the following transcription: "{raw_text}"

Instructions:
- The text might contain phonetic hallucinations, weird translations, or Cyrillic transliterations (e.g., 'свеики', 'скандинув', 'лабас' sounds like 'sveiki, skambinu, labas').
- If it sounds like Lithuanian phonetics (even written in Cyrillic) or has clear Lithuanian context, return 'LT'.
- Otherwise, return 'RU'.
- Output ONLY TWO LETTERS: LT or RU. Do not explain anything."""

       classification_res = await groq_client.chat.completions.create(
          model="llama-3.1-8b-instant",  # <--- АКТУАЛЬНАЯ БЫСТРАЯ МОДЕЛЬ (Избегаем 400 ошибки)
          messages=[{"role": "user", "content": classifier_prompt}],
          temperature=0.0
       )

       lang_decision = classification_res.choices[0].message.content.strip().upper()

       if "LT" in lang_decision:
          print(f"✅ [DETECTOR] LLM постановила: LT (Анализ текста: {raw_text})")
          return "LT", raw_text
       else:
          print(f"✅ [DETECTOR] LLM постановила: RU (Анализ текста: {raw_text})")
          return "RU", raw_text

    except Exception as e:
       print(f"❌ [DETECTOR] Ошибка: {e}")
       return "RU", ""