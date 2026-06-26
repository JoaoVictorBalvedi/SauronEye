import json
from datetime import date
import gspread
from google.oauth2.service_account import Credentials
from config import get_settings


def _get_credentials():
    settings = get_settings()
    content = settings["service_account_content"]
    if content:
        info = json.loads(content)
        return Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
    return Credentials.from_service_account_file(
        settings["service_account_file"],
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )


def _get_client():
    return gspread.authorize(_get_credentials())


HEADERS = ["Nome", "Valor", "Data", "Categoria", "Quem fez a compra", "Forma de Pagamento", "Observações"]


def append_transaction(sheet_id: str, transaction: dict):
    client = _get_client()
    sheet = client.open_by_key(sheet_id).sheet1

    if sheet.row_values(1) != HEADERS:
        sheet.insert_row(HEADERS, 1)

    sheet.append_row([
        transaction.get("nome", ""),
        transaction.get("valor", 0),
        transaction.get("data", str(date.today())),
        transaction.get("categoria", ""),
        transaction.get("quem_fez", ""),
        transaction.get("forma_pagamento", ""),
        transaction.get("observacoes", ""),
    ])


def read_transactions(sheet_id: str) -> str:
    client = _get_client()
    sheet = client.open_by_key(sheet_id).sheet1
    rows = sheet.get_all_values()
    if not rows:
        return "Nenhuma transação encontrada."
    data = rows[1:]
    if not data:
        return "Nenhuma transação encontrada."
    lines = [" | ".join(rows[0])]
    lines.append("-" * 60)
    for row in data:
        lines.append(" | ".join(row))
    return "\n".join(lines)
