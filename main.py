import time
import subprocess
import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from config import get_settings
from db import init_db
from bot import extract_message, handle_message
from ai_parser import close_llm

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def check_ollama():
    settings = get_settings()
    url = settings["ollama_url"]
    model = settings["llm_model"]

    try:
        httpx.get(f"{url}/api/tags", timeout=5)
    except httpx.RequestError:
        logger.info("Ollama not running. Starting it...")
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        for _ in range(15):
            time.sleep(1)
            try:
                httpx.get(f"{url}/api/tags", timeout=2)
                break
            except httpx.RequestError:
                continue
        else:
            logger.error("Failed to start Ollama.")
            raise RuntimeError("Failed to start Ollama")

        logger.info("Ollama started.")

    models = httpx.get(f"{url}/api/tags", timeout=5).json().get("models", [])

    if not any(model in m.get("name", "") for m in models):
        logger.info("Pulling model '%s'...", model)
        subprocess.run(["ollama", "pull", model], check=True)
        logger.info("Done.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    check_ollama()
    logger.info("Bot ready. Webhook endpoint at /webhook")
    yield
    await close_llm()
    logger.info("Shutting down.")


app = FastAPI(lifespan=lifespan)


@app.post("/webhook")
async def webhook(request: Request):
    try:
        data = await request.json()
        logger.info("Webhook received: %s", data)

        chat_id, text = extract_message(data)

        if not chat_id or not text:
            return {"ok": True}

        reply = await handle_message(chat_id, text)

        return JSONResponse(
            {
                "method": "sendMessage",
                "chat_id": chat_id,
                "text": reply,
            }
        )

    except Exception:
        logger.exception("Webhook error")
        return {"ok": True}


@app.get("/")
@app.get("/health")
async def health():
    return {"status": "ok"}
