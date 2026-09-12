import logging
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from utils import send_discord_alert
from api_pbx import router as pbx_router
from api_web import router as web_router
from pbx_socket import start_audiosocket_server

logging.basicConfig(level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
	# Запускаем наш TCP-сервер AudioSocket в фоне
	socket_task = asyncio.create_task(start_audiosocket_server())

	# Никаких больше фейковых SIP-агентов!
	# Asterisk сделает всю грязную работу, а мы просто сообщаем о старте.
	await send_discord_alert("🟢 SYSTEM ONLINE", "**Architecture V2 (Asterisk + Modular)** Active.", 3066993)
	yield
	await send_discord_alert("🔴 SYSTEM OFFLINE", "Shutting down.", 15158332)

	# Тормозим сокет при выключении сервера
	socket_task.cancel()


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