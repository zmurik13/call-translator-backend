import os
import io
import asyncio
from dotenv import load_dotenv
from groq import AsyncGroq
from openai import AsyncOpenAI
import edge_tts

# === ЗАГРУЗКА .ENV ===
# Ищет файл .env в папке и принудительно загружает ключи
load_dotenv()

# === API КЛЮЧИ И КЛИЕНТЫ ===
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")

# Уши (STT) - Возвращаем бесплатный и быстрый Groq
groq_client = AsyncGroq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# Мозги (LLM) - Направляем клиента OpenAI в OpenRouter
or_client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

# === КОНСТАНТЫ И ПРОМПТЫ ===
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

# === УМНЫЙ РОУТЕР LLM С ЗАПАСКОЙ ===
async def _call_llm(messages, temperature=0.2):
    """Вызывает стабильную Llama 3 через Groq API."""
    try:
        res = await groq_client.chat.completions.create(
            model="llama3-8b-8192",  # <-- Стабильная базовая модель Groq
            messages=messages,
            temperature=temperature
        )
        return res.choices[0].message.content.strip()
    except Exception as e:
        print(f"⚠️ [LLM] Llama3-8b не ответила ({e}). Переключаюсь на Mixtral...")
        try:
            res = await groq_client.chat.completions.create(
                model="mixtral-8x7b-32768",  # <-- Запасная модель Groq
                messages=messages,
                temperature=temperature
            )
            return res.choices[0].message.content.strip()
        except Exception as fallback_err:
            print(f"❌ [LLM] Ошибка обоих LLM-моделей: {fallback_err}")
            return "[LLM Error]"

# === ФУНКЦИИ ЯДРА ===

async def transcribe_audio(audio_bytes, file_name, content_type, source_lang):
    """Распознает звук от любого источника через Groq (Whisper-Turbo)."""
    prompts = {"ru": PROMPT_RU, "lt": PROMPT_LT, "pl": PROMPT_PL}
    current_prompt = prompts.get(source_lang, PROMPT_RU)

    try:
       res = await groq_client.audio.transcriptions.create(
          file=(file_name, audio_bytes, content_type),
          model="whisper-large-v3-turbo",
          prompt=current_prompt,
          language=source_lang,
          response_format="text"
       )
       text = res.strip()
       lower_text = text.lower().strip('.?!, ')

       if not lower_text or any(h in lower_text for h in HALLUCINATIONS) or lower_text in ["ačiū", "спасибо", "привет", "labas", "dzięki"]:
          return "[Тишина / Шум]", True

       return text, False
    except Exception as e:
       print(f"❌ [STT Error]: {e}")
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
4. Output ONLY the final translated text. No explanations."""

    messages = [
        {"role": "system", "content": web_system_prompt},
        {"role": "user", "content": f"Source text: {raw_text}"}
    ]
    return await _call_llm(messages, temperature=0.2)


async def generate_speech(text, target_lang):
    """Генерирует MP3 поток через Edge-TTS (с хаком для паузы)."""
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
    """Детектор языка: уши от Whisper (Groq), мозги от OpenRouter."""
    try:
       greetings_prompt = (
          "Taip, klausau. Labas rytas, laba diena, labas vakaras. "
          "Sveiki, skambinu dėl padangų, ratų bazė. Noriu paklausti, kiek kainuoja, "
          "ar turite laisvo laiko, noriu užsiregistruoti, pakeisti."
       )

       # 1. STT: Слушаем через Groq
       res = await groq_client.audio.transcriptions.create(
          file=(file_name, audio_bytes, content_type),
          model="whisper-large-v3-turbo",
          prompt=greetings_prompt,
          temperature=0.0,
          response_format="text"
       )

       raw_text = res.strip()
       print(f"🕵️ [DETECTOR] Whisper услышал текст: '{raw_text}'")

       if not raw_text:
          return "RU", "[Тишина / Шум]"

       # 2. LLM MAGIC: Классифицируем через умный fallback
       classifier_prompt = f"""You are a language detection router for an auto service in Lithuania.
Analyze the following transcription: "{raw_text}"

Instructions:
- The text might contain phonetic hallucinations, weird translations, or Cyrillic transliterations (e.g., 'свеики', 'скандинув', 'лабас' sounds like 'sveiki, skambinu, labas').
- If it sounds like Lithuanian phonetics (even written in Cyrillic) or has clear Lithuanian context, return 'LT'.
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