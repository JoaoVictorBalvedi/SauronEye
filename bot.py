import asyncio
import json
import re
import logging

from config import get_settings
from db import get_user, create_user, set_sheet_id, set_sheet_headers, complete_registration
from ai_parser import classify_and_parse, answer_query
from sheets import read_headers, append_transaction, read_transactions
from ratelimit import RateLimiter

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

    settings = get_settings()
    sa_email = settings["service_account_email"]
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
        try:
            headers = await asyncio.to_thread(read_headers, text)
        except Exception:
            logger.exception("Failed to read sheet headers")
            return (
                "Não consegui acessar sua planilha. 😅\n\n"
                "Verifique se:\n"
                f"1. Você compartilhou com {sa_email} como Editor\n"
                "2. O ID está correto\n\n"
                "Depois tente novamente!"
            )
        set_sheet_id(chat_id, text)
        set_sheet_headers(chat_id, headers)
        cols = ", ".join(headers)
        return (
            f"Planilha encontrada! ✅\n\n"
            f"Colunas detectadas: {cols}\n\n"
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
        headers = user.get("sheet_headers")

        if not headers:
            headers = await asyncio.to_thread(read_headers, user["sheet_id"])
            set_sheet_headers(chat_id, headers)
        elif isinstance(headers, str):
            headers = json.loads(headers)

        intent, transaction = await classify_and_parse(text, headers)

        if intent == "record":
            await asyncio.to_thread(
                append_transaction, user["sheet_id"], transaction, headers
            )
            return "Registrado! ✅"

        sheet_data = await asyncio.to_thread(read_transactions, user["sheet_id"])
        return await answer_query(text, sheet_data)

    except Exception:
        logger.exception("Handler error")
        return "Erro interno. Tente novamente."
