import os
import random
import io
import asyncio
import logging
import httpx
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, UploadFile, File, Form, BackgroundTasks
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from groq import AsyncGroq
import edge_tts

# =====================================================================
# LOGGING CONFIGURATION
# =====================================================================

# Configure base logging for Render console
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("translator_gateway")

# 1. Silence the overly talkative httpx logger (only show warnings/errors)
logging.getLogger("httpx").setLevel(logging.WARNING)

# 2. Create a custom filter to hide /ping requests from Uvicorn access logs
class EndpointFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Ignore any log message containing "/ping"
        return record.getMessage().find("/ping") == -1

# Apply the filter to the uvicorn access logger
logging.getLogger("uvicorn.access").addFilter(EndpointFilter())

# =====================================================================
# ENVIRONMENT VARIABLES & CLIENTS
# =====================================================================

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")

groq_client = AsyncGroq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# =====================================================================
# HELPER FUNCTIONS
# =====================================================================

async def send_discord_alert(title: str, message: str, color: int = 3447003):
    """Sends rich embed alerts to Discord Webhook."""
    if not DISCORD_WEBHOOK_URL:
        return
    payload = {
        "embeds": [{
            "title": title,
            "description": message,
            "color": color
        }]
    }
    async with httpx.AsyncClient() as client:
        try:
            await client.post(DISCORD_WEBHOOK_URL, json=payload)
        except Exception as e:
            print(f"❌ Failed to send Discord alert: {e}", flush=True)

# =====================================================================
# FUNNY SYSADMIN QUOTES FOR DISCORD LOGS
# =====================================================================

STARTUP_MESSAGES = [
    "Новая смена заступила! ☕",
    "Свежий билд в продакшене. Полет нормальный. 🚀",
    "Я родился! И готов переводить. 🤖",
    "Новый контейнер поднялся. Все системы в норме. 🟢",
    "Матрица перезагружена. Агент Смит на связи. 🕶️"
]

SHUTDOWN_MESSAGES = [
    "Старая смена ушла домой. 🍺",
    "Моё время пришло... Отключаюсь. 🥀",
    "Контейнер устал, контейнер уходит спать. 🛌",
    "Ушёл в Вальхаллу для серверов. ⚔️",
    "Я не говорю прощай, я говорю 'до нового билда'. 🫡"
]

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fetch the commit hash once when the app starts
    commit_hash = os.environ.get("RENDER_GIT_COMMIT", "unknown")[:7]
    
    # Pick a random funny message for startup
    startup_joke = random.choice(STARTUP_MESSAGES)
    
    # Triggered on application startup
    await send_discord_alert(
        "🟢 SYSTEM ONLINE", 
        f"**Build:** `{commit_hash}`\n_{startup_joke}_", 
        3066993
    )
    
    yield
    
    # Pick a random funny message for shutdown
    shutdown_joke = random.choice(SHUTDOWN_MESSAGES)
    
    # Triggered on graceful application shutdown
    await send_discord_alert(
        "🔴 SYSTEM OFFLINE", 
        f"**Build:** `{commit_hash}`\n_{shutdown_joke}_", 
        15158332
    )

# =====================================================================
# FASTAPI APP INITIALIZATION
# =====================================================================

app = FastAPI(title="Real-Time Voice Translator", lifespan=lifespan)

# Mount static folder for CSS, JS, and HTML
app.mount("/static", StaticFiles(directory="static"), name="static")

# =====================================================================
# PROMPTS & CONFIGURATION
# =====================================================================

# Strict grammar, punctuation, and PHONETIC TYPO correction prompt
SYSTEM_PROMPT = """You are an elite, ultra-fast speech translator between Russian and Lithuanian.
CRITICAL INSTRUCTIONS:
The input comes from a Speech-to-Text system (Whisper). It often contains phonetic typos (like 'lietai' instead of 'lėtai') or misheard words due to background noise.

Your processing pipeline:
1. FIX TYPOS & CONTEXT FIRST: If a word sounds phonetically similar to a logical word but was transcribed incorrectly by STT, reconstruct the intended meaning based on context. Do NOT invent nationalities, weird concepts, or literal translations of STT glitches.
2. Translate the corrected meaning to the OTHER language (If input is Russian -> Lithuanian. If input is Lithuanian -> Russian).
3. GRAMMAR STRICTNESS: Ensure absolute grammatical perfection and natural phrasing.
4. PUNCTUATION FOR TTS: Apply flawless punctuation (periods, commas, question marks).
5. Output ONLY the final translated text. No explanations, no quotes."""

PROMPT_RU = "Привет! Проверяем, как всё работает. Рату базе, я звоню насчет шиномонтажа. Продажа шин, автосервис, балансировка. Какая цена? Сколько стоит шиномонтаж? Да, я понял. Доброе утро. Проверка связи."
PROMPT_LT = "Labas rytas. Laba diena. Ratų bazė. Padangų montavimas, ratų balansavimas, padangų keitimas. Kokia kaina? Kiek kainuoja? Užsiregistruoti, patikrinti. Gerai, patikrinam, kaip viskas veikia. Kodėl taip lėtai? Automobilis, mašina, ratlankiai, servisas. Taip, supratau. Ačiū. Ryšio patikrinimas."

VOICE_MAP = {
    "lt": "lt-LT-LeonasNeural",
    "ru": "ru-RU-DmitryNeural"
}

# Blacklist for common Whisper silence hallucinations
WHISPER_HALLUCINATIONS = [
    "продолжение следует",
    "подписывайтесь на канал",
    "to be continued",
    "subtitles by",
    "amara.org",
    "спасибо за просмотр",
    "dėkis",
    "dėkis."
]

# =====================================================================
# ENDPOINTS
# =====================================================================

@app.get("/ping")
async def keep_alive_ping():
    """Endpoint for UptimeRobot to keep the Render container awake."""
    return {"status": "alive", "message": "Ready to translate!"}

@app.api_route("/zadarma-webhook", methods=["GET", "POST"])
async def zadarma_webhook_handler(request: Request, background_tasks: BackgroundTasks):
    """Handles incoming webhooks from Zadarma PBX."""
    zd_echo = request.query_params.get("zd_echo")
    if zd_echo:
        return PlainTextResponse(content=zd_echo, status_code=200)

    data = await request.form() if request.method == "POST" else request.query_params
    event_type = data.get("event")
    caller_id = data.get("caller_id") or data.get("caller_id_name")
    called_did = data.get("called_did")

    if event_type == "NOTIFY_START":
        msg = f"**Caller:** `{caller_id}`\n**Destination:** `{called_did}`"
        print(f"\n📞 [ZADARMA] New Call from {caller_id} to {called_did}", flush=True)
        background_tasks.add_task(send_discord_alert, "📞 New Incoming Call", msg, 5763719)

    return PlainTextResponse(content="OK", status_code=200)

@app.post("/api/translate-voice")
async def process_voice_translation(
        background_tasks: BackgroundTasks,
        audio: UploadFile = File(...),
        source_lang: str = Form(...),
        device_info: str = Form("Unknown Device")
):
    """Core pipeline: STT -> LLM -> TTS with silence fallback."""
    if not groq_client:
        return PlainTextResponse(content="GROQ_API_KEY is not configured", status_code=500)

    audio_bytes = await audio.read()

    if len(audio_bytes) == 0:
        print(f"⚠️ [WARNING] Empty audio received from {device_info}", flush=True)
        background_tasks.add_task(
            send_discord_alert, 
            "⚠️ Empty Audio Warning", 
            f"Received 0 bytes.\n\n**Device Data:**\n{device_info}", 
            16753920
        )
        return PlainTextResponse(content="Error: Audio file is empty.", status_code=400)

    file_ext = "mp4" if "mp4" in audio.content_type or "m4a" in audio.filename else "webm"
    current_prompt = PROMPT_RU if source_lang == "ru" else PROMPT_LT

    # 1. STT via Groq Whisper with iOS crash protection and Smart Filter
    is_silence = False
    try:
        stt_response = await groq_client.audio.transcriptions.create(
            file=(f"record.{file_ext}", audio_bytes, audio.content_type),
            model="whisper-large-v3",
            prompt=current_prompt,
            language=source_lang,
            response_format="text"
        )
        recognized_text = stt_response.strip()
        recognized_lower = recognized_text.lower().strip('.?!, ')
        
        # Smart hallucination filter
        if not recognized_lower:
            is_silence = True
        else:
            for h in WHISPER_HALLUCINATIONS:
                if h in recognized_lower:
                    is_silence = True
                    break
            
            if recognized_lower in ["ačiū", "спасибо", "привет", "labas", "dėkis"]:
                is_silence = True

        if is_silence:
            print(f"👻 [FILTER] Ignored silence or hallucination: '{recognized_text}'", flush=True)
            
    except Exception as e:
        print(f"⚠️ [STT ERROR] Groq rejected audio (likely iOS glitch): {e}", flush=True)
        recognized_text = ""
        is_silence = True

    # 2. Translation Logic (Bypass LLM if silence detected)
    if is_silence:
        if source_lang == "ru":
            recognized_text = "[Тишина / Шум]"
            translated_text = "Atsiprašau, neišgirdau. Pakartokite, prašau."
            selected_voice = VOICE_MAP["lt"]
        else:
            recognized_text = "[Tyla / Triukšmas]"
            translated_text = "Извините, я вас не расслышал. Повторите, пожалуйста."
            selected_voice = VOICE_MAP["ru"]

        print(f"🔇 [SILENCE] Sending polite fallback to TTS.", flush=True)
        log_msg = f"**Source ({source_lang.upper()}):** {recognized_text}\n**Action:** Triggered silence fallback.\n\n**Device Data:**\n{device_info}"
        background_tasks.add_task(send_discord_alert, "🔇 Silence Detected", log_msg, 16753920)

    else:
        llm_response = await groq_client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Source text: {recognized_text}"}
            ],
            temperature=0.2
        )
        translated_text = llm_response.choices[0].message.content.strip()
        selected_voice = VOICE_MAP["lt"] if source_lang == "ru" else VOICE_MAP["ru"]

        # Formatted console output for Render logs
        print("\n" + "=" * 50, flush=True)
        print(f"🎙️ RECOGNIZED ({source_lang.upper()}): {recognized_text}", flush=True)
        print(f"🔄 TRANSLATED: {translated_text}", flush=True)
        print("-" * 50, flush=True)
        print(f"📡 DEVICE INFO:\n{device_info}", flush=True)
        print("=" * 50 + "\n", flush=True)

        # Formatted Discord output
        log_msg = f"**Source ({source_lang.upper()}):** {recognized_text}\n**Translated:** {translated_text}\n\n**Device Data:**\n{device_info}"
        background_tasks.add_task(send_discord_alert, "🗣️ Translation Log", log_msg, 3447003)

        if not translated_text:
            error_msg = f"LLM returned empty string.\n**Input:** `{recognized_text}`\n\n**Device Data:**\n{device_info}"
            background_tasks.add_task(send_discord_alert, "🚨 LLM Translation Failed", error_msg, 15548997)
            translated_text = "Atsiprašau, sistemos klaida." if source_lang == "ru" else "Извините, системная ошибка."

    # 3. Text-to-Speech (with Auto-Retry mechanism)
    audio_stream = io.BytesIO()
    tts_success = False

    for attempt in range(3):
        try:
            tts = edge_tts.Communicate(translated_text, selected_voice)
            async for chunk in tts.stream():
                if chunk["type"] == "audio":
                    audio_stream.write(chunk["data"])

            if audio_stream.tell() > 0:
                tts_success = True
                break
            else:
                raise Exception("Empty audio stream received")
        except Exception as e:
            print(f"⚠️ [TTS WARNING] Microsoft Edge TTS failed on attempt {attempt + 1}: {e}", flush=True)
            await asyncio.sleep(0.5)

    if not tts_success:
        print("🚨 [FATAL ERROR] Edge-TTS completely failed after 3 attempts.", flush=True)
        background_tasks.add_task(
            send_discord_alert,
            "🚨 TTS Failed",
            f"Edge-TTS blocked the request.\n**Text:** `{translated_text}`",
            15548997
        )
        return PlainTextResponse(content="Error: TTS generation failed.", status_code=500)

    audio_stream.seek(0)
    headers = {
        "X-Recognized-Text": recognized_text.encode("unicode_escape").decode("utf-8"),
        "X-Translated-Text": translated_text.encode("unicode_escape").decode("utf-8")
    }
    return StreamingResponse(audio_stream, media_type="audio/mpeg", headers=headers)

@app.get("/", response_class=HTMLResponse)
async def serve_interface():
    """Serve the static HTML interface."""
    return FileResponse("static/index.html")
