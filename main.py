import os
import re
import time
import subprocess
import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from telegram import Bot, Update

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

bot: Bot | None = None


async def handle_message(update: Update):
    chat_id = str(update.effective_chat.id)
    text = update.message.text.strip()

    if not _limiter.check(chat_id):
        await update.message.reply_text(
            "Calma aí! Você está mandando mensagens muito rápido. "
            "Aguarda um pouco e tenta de novo. 😅"
        )
        return
    sa_email = get_settings()["service_account_email"]

    user = get_user(chat_id)

    if not user:
        create_user(chat_id)
        await update.message.reply_text(
            f"Olá! 😊 Antes de começarmos, preciso que você compartilhe "
            f"sua planilha do Google Sheets com o email abaixo com permissão de **Editor**:\n\n"
            f"`{sa_email}`\n\n"
            f"Depois, me envie o **ID da planilha**.\n"
            f"Ele está na URL: `.../d/`**ID_AQUI**`/edit`"
        )
        return

    if user["reg_state"] == "awaiting_sheet":
        if not SHEET_ID_PATTERN.match(text):
            await update.message.reply_text(
                f"Esse não parece um ID válido. 🙃\n\n"
                f"O ID fica na URL da sua planilha, exemplo:\n"
                f"`docs.google.com/spreadsheets/d/`**abc123...**`/edit`\n\n"
                f"Compartilhe a planilha com `{sa_email}` como **Editor** e me envie o ID!"
            )
            return
        set_sheet_id(chat_id, text)
        await update.message.reply_text(
            "Planilha encontrada! ✅\n\n"
            "Agora me informe seu **email** para eu associar sua conta:"
        )
        return

    if user["reg_state"] == "awaiting_email":
        if not EMAIL_PATTERN.match(text):
            await update.message.reply_text(
                "Esse não parece um email válido. 😅\n"
                "Me envia um email tipo: `seu@email.com`"
            )
            return
        complete_registration(chat_id, text)
        await update.message.reply_text(
            "Tudo pronto! 🎉\n\n"
            "Agora é só mandar seus gastos que eu registro na planilha.\n"
            "Exemplos:\n"
            "- *gasolina 50 reais*\n"
            "- *paguei 25 no ifood*\n"
            "- *quanto gastei esse mês?*"
        )
        return

    try:
        intent = await classify_intent(text)

        if intent == "record":
            transaction = await parse_message(text)
            append_transaction(user["sheet_id"], transaction)
            await update.message.reply_text(
                f"Registrado: {transaction['nome']} — "
                f"R${transaction['valor']:.2f} ({transaction['categoria']})"
            )
        else:
            sheet_data = read_transactions(user["sheet_id"])
            answer = await answer_query(text, sheet_data)
            await update.message.reply_text(answer)

    except Exception as e:
        logger.error("Handler error: %s", e)
        await update.message.reply_text("Erro interno. Tente novamente.")


def check_ollama():
    settings = get_settings()
    url = settings["ollama_url"]
    model = settings["llm_model"]

    try:
        httpx.get(f"{url}/api/tags", timeout=5)
    except httpx.RequestError:
        logger.info("Ollama not running. Starting it...")
        subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(15):
            time.sleep(1)
            try:
                httpx.get(f"{url}/api/tags", timeout=2)
                break
            except httpx.RequestError:
                continue
        else:
            logger.error("Failed to start Ollama.")
            exit(1)
        logger.info("Ollama started.")

    models = httpx.get(f"{url}/api/tags", timeout=5).json().get("models", [])
    if not any(model in m.get("name", "") for m in models):
        logger.info("Pulling model '%s'...", model)
        subprocess.run(["ollama", "pull", model])
        logger.info("Done.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global bot

    init_db()
    check_ollama()

    settings = get_settings()
    bot = Bot(token=settings["bot_token"], base_url=settings["telegram_api_url"])

    logger.info("Bot ready. Webhook endpoint at /webhook")
    yield

    logger.info("Shutting down.")


app = FastAPI(lifespan=lifespan)


@app.post("/webhook")
async def webhook(request: Request):
    global bot
    try:
        data = await request.json()
        update = Update.de_json(data, bot)
        await handle_message(update)
    except Exception as e:
        logger.error("Webhook error: %s", e)
    return {"ok": True}


@app.get("/")
@app.get("/health")
async def health():
    return {"status": "ok"}
