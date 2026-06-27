import re
import time
import subprocess
import httpx
from telegram import Update
from telegram.ext import Application, MessageHandler, filters
from telegram.request import HTTPXRequest
from config import get_settings
from db import init_db, get_user, create_user, set_sheet_id, complete_registration
from ai_parser import classify_intent, parse_message, answer_query
from sheets import append_transaction, read_transactions
from ratelimit import RateLimiter

SHEET_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{40,50}$")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_limiter = RateLimiter()


async def handle_message(update: Update, _):
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
        print(f"[ERROR] {e}")
        await update.message.reply_text("Erro interno. Tente novamente.")


def check_ollama():
    settings = get_settings()
    url = settings["ollama_url"]
    model = settings["llm_model"]

    try:
        httpx.get(f"{url}/api/tags", timeout=5)
    except httpx.RequestError:
        print("Ollama not running. Starting it...")
        subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(15):
            time.sleep(1)
            try:
                httpx.get(f"{url}/api/tags", timeout=2)
                break
            except httpx.RequestError:
                continue
        else:
            print("Failed to start Ollama. Start it manually: ollama serve")
            exit(1)
        print("Ollama started.")

    models = httpx.get(f"{url}/api/tags", timeout=5).json().get("models", [])
    if not any(model in m.get("name", "") for m in models):
        print(f"Pulling model '{model}'...")
        subprocess.run(["ollama", "pull", model])
        print("Done.")


def wait_for_telegram(token: str, max_retries: int = 5, delay: int = 10):
    url = f"https://api.telegram.org/bot{token}/getMe"
    for attempt in range(1, max_retries + 1):
        try:
            r = httpx.get(url, timeout=15)
            if r.status_code == 200:
                return
            print(f"[{attempt}/{max_retries}] Telegram returned {r.status_code}. Retrying in {delay}s...")
        except httpx.RequestError as e:
            print(f"[{attempt}/{max_retries}] Telegram unreachable: {e}. Retrying in {delay}s...")
        time.sleep(delay)
    print("Could not reach Telegram API after all retries. Exiting.")
    exit(1)


def main():
    init_db()
    check_ollama()
    settings = get_settings()
    wait_for_telegram(settings["bot_token"])
    request = HTTPXRequest(connect_timeout=60, read_timeout=60)
    app = Application.builder().token(settings["bot_token"]).request(request).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()


if __name__ == "__main__":
    main()
