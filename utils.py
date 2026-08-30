import os
import httpx

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")

async def send_discord_alert(title: str, message: str, color: int = 3447003):
    if not DISCORD_WEBHOOK_URL:
        return
    payload = {"embeds": [{"title": title, "description": message, "color": color}]}
    async with httpx.AsyncClient() as client:
        try:
            await client.post(DISCORD_WEBHOOK_URL, json=payload)
        except Exception as e:
            print(f"❌ Discord alert failed: {e}", flush=True)