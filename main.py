import re
import time
import subprocess
import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from config import get_settings
from db import init_db, get_user, create_user, set_sheet_id, complete_registration
from ai_parser import classify_intent, parse_message, answer_query
from sheets import append_transaction, read_transactions
from ratelimit import RateLimiter

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SHEET_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{40,50}$")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_limiter = RateLimiter()


def extract_message(data: dict) -> tuple[str | None, str | None]:
    message = data.get("message") or data.get("edited_message")

    if not message:
        return None, None

    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    text = message.get("text")

    if chat_id is None or not text:
        return None, None

    return str(chat_id), text.strip()


async def handle_message(chat_id: str, text: str) -> str:
    if not _limiter.check(chat_id):
        return (
            "Calma aí! Você está mandando mensagens muito rápido. "
            "Aguarda um pouco e tenta de novo. 😅"
        )

    sa_email = get_settings()["service_account_email"]
    user = get_user(chat_id)

    if not user:
        create_user(chat_id)
        return (
            "Olá! 😊 Antes de começarmos, preciso que você compartilhe "
            "sua planilha do Google Sheets com o email abaixo com permissão de Editor:\n\n"
            f"{sa_email}\n\n"
            "Depois, me envie o ID da planilha.\n"
            "Ele está na URL: .../d/ID_AQUI/edit"
        )

    if user["reg_state"] == "awaiting_sheet":
        if not SHEET_ID_PATTERN.match(text):
            return (
                "Esse não parece um ID válido. 🙃\n\n"
                "O ID fica na URL da sua planilha, exemplo:\n"
                "docs.google.com/spreadsheets/d/abc123.../edit\n\n"
                f"Compartilhe a planilha com {sa_email} como Editor e me envie o ID!"
            )

        set_sheet_id(chat_id, text)
        return (
            "Planilha encontrada! ✅\n\n"
            "Agora me informe seu email para eu associar sua conta:"
        )

    if user["reg_state"] == "awaiting_email":
        if not EMAIL_PATTERN.match(text):
            return (
                "Esse não parece um email válido. 😅\n"
                "Me envia um email tipo: seu@email.com"
            )

        complete_registration(chat_id, text)
        return (
            "Tudo pronto! 🎉\n\n"
            "Agora é só mandar seus gastos que eu registro na planilha.\n"
            "Exemplos:\n"
            "- gasolina 50 reais\n"
            "- paguei 25 no ifood\n"
            "- quanto gastei esse mês?"
        )

    try:
        intent = await classify_intent(text)

        if intent == "record":
            transaction = await parse_message(text)
            append_transaction(user["sheet_id"], transaction)
            return (
                f"Registrado: {transaction['nome']} — "
                f"R${transaction['valor']:.2f} ({transaction['categoria']})"
            )

        sheet_data = read_transactions(user["sheet_id"])
        return await answer_query(text, sheet_data)

    except Exception:
        logger.exception("Handler error")
        return "Erro interno. Tente novamente."


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