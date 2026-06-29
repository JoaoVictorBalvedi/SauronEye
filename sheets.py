import json
from functools import lru_cache

import gspread
from google.oauth2.service_account import Credentials
from config import get_settings


@lru_cache
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


@lru_cache
def _get_client():
    return gspread.authorize(_get_credentials())


def read_headers(sheet_id: str) -> list[str]:
    client = _get_client()
    sheet = client.open_by_key(sheet_id).sheet1
    return sheet.row_values(1)


def append_transaction(sheet_id: str, transaction: dict, headers: list[str]):
    client = _get_client()
    sheet = client.open_by_key(sheet_id).sheet1

    if sheet.row_values(1) != headers:
        sheet.insert_row(headers, 1)

    row = []
    for h in headers:
        val = transaction.get(h)
        row.append(val if val is not None else "")
    sheet.append_row(row)


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
