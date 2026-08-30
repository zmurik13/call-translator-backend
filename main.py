import logging
import threading
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from utils import send_discord_alert
from api_pbx import router as pbx_router
from api_web import router as web_router

# ВОТ ОН, НАШ ГЕРОЙ, КОТОРЫЙ БЕРЕТ ТРУБКУ
from sip_agent import start_sip_client

logging.basicConfig(level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
	# ЗАПУСКАЕМ ЗВОНИЛКУ В ОТДЕЛЬНОМ ПОТОКЕ
	sip_thread = threading.Thread(target=start_sip_client, daemon=True)
	sip_thread.start()

	await send_discord_alert("🟢 SYSTEM ONLINE", "**Architecture V2 (Modular)** Active.", 3066993)
	yield
	await send_discord_alert("🔴 SYSTEM OFFLINE", "Shutting down.", 15158332)


app = FastAPI(title="Real-Time Voice Translator", lifespan=lifespan)

app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(pbx_router)
app.include_router(web_router)


@app.get("/ping")
async def keep_alive_ping():
	return {"status": "alive", "message": "Ready to translate!"}


@app.get("/", response_class=HTMLResponse)
async def serve_interface():
	return FileResponse("static/index.html")


if __name__ == "__main__":
	import uvicorn

	uvicorn.run(app, host="127.0.0.1", port=8000)