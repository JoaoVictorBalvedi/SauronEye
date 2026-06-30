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

    # Headers are cached at registration time (db.sheet_headers) and trusted
    # here, skipping a verification read on every single write.
    row = []
    for h in headers:
        val = transaction.get(h)
        row.append(val if val is not None else "")
    sheet.append_row(row)


_MAX_QUERY_ROWS = 40


def read_transactions(sheet_id: str, max_rows: int = _MAX_QUERY_ROWS) -> str:
    client = _get_client()
    sheet = client.open_by_key(sheet_id).sheet1

    # Only column A is read to find the last populated row, instead of
    # pulling the entire sheet history just to look at the last few rows.
    last_row = len(sheet.col_values(1))
    if last_row <= 1:
        return "Nenhuma transação encontrada."

    start = max(2, last_row - max_rows + 1)
    header_grid, data_grid = sheet.batch_get(["A1:Z1", f"A{start}:Z{last_row}"])
    if not header_grid or not header_grid[0]:
        return "Nenhuma transação encontrada."

    lines = [" | ".join(header_grid[0])]
    lines.append("-" * 60)
    for row in data_grid:
        if any(cell.strip() for cell in row):
            lines.append(" | ".join(row))
    return "\n".join(lines)
