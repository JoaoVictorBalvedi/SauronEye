import time
import subprocess
import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import BackgroundTasks, FastAPI, Request

from config import get_settings
from db import init_db
from bot import extract_message, handle_message
from ai_parser import close_llm

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_proxy = get_settings()["telegram_proxy_url"]
_telegram_client = httpx.AsyncClient(timeout=httpx.Timeout(15), proxy=_proxy)


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
    await _telegram_client.aclose()
    logger.info("Shutting down.")


app = FastAPI(lifespan=lifespan)


async def _process_and_reply(chat_id: str, text: str):
    try:
        reply = await handle_message(chat_id, text)
    except Exception:
        logger.exception("Handler error")
        reply = "Erro interno. Tente novamente."

    settings = get_settings()
    url = f"{settings['telegram_api_url']}{settings['bot_token']}/sendMessage"
    try:
        await _telegram_client.post(url, json={"chat_id": chat_id, "text": reply})
    except httpx.HTTPError:
        logger.exception("Failed to send Telegram reply")


@app.post("/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        data = await request.json()

        chat_id, text = extract_message(data)

        if not chat_id or not text:
            return {"ok": True}

        # Ack Telegram immediately. Processing (LLM + Sheets calls) can take
        # well over Telegram's webhook response window on slow hardware; if we
        # don't reply fast, Telegram retries the same update and re-runs the
        # whole expensive pipeline again, multiplying latency.
        background_tasks.add_task(_process_and_reply, chat_id, text)
        return {"ok": True}

    except Exception:
        logger.exception("Webhook error")
        return {"ok": True}


@app.get("/")
@app.get("/health")
async def health():
    return {"status": "ok"}
