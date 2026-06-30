import json
from datetime import date

import httpx
from config import get_settings

_MAX_TEXT_LENGTH = 500

_client = httpx.AsyncClient(timeout=httpx.Timeout(120))


async def close_llm():
    await _client.aclose()


async def _llm(prompt: str, json_mode: bool = False, max_tokens: int = 250) -> str:
    settings = get_settings()
    body = {
        "model": settings["llm_model"],
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        # Keep the model resident between requests so we don't pay Ollama's
        # load time on every message.
        "keep_alive": "30m",
        # Bounds worst-case generation time on slow (CPU-only) hosts; these
        # responses are always short (a JSON object or a brief answer).
        "options": {"num_predict": max_tokens},
    }
    if json_mode:
        body["format"] = "json"
    resp = await _client.post(
        f"{settings['ollama_url']}/api/chat", json=body
    )
    resp.raise_for_status()
    return resp.json()["message"]["content"]


_COLUMN_HINTS: dict[str, str] = {
    "valor": "valor numérico positivo, sem R$ nem símbolos",
    "preço": "valor numérico positivo, sem R$ nem símbolos",
    "preco": "valor numérico positivo, sem R$ nem símbolos",
    "value": "positive numeric value, no currency symbols",
    "amount": "positive numeric value, no currency symbols",
    "data": "data no formato YYYY-MM-DD",
    "date": "date in YYYY-MM-DD format",
    "dia": "data no formato YYYY-MM-DD",
    "categoria": "categoria baseada no contexto da compra",
    "category": "category based on purchase context",
    "nome": "nome do item ou descrição curta",
    "name": "item name or short description",
    "descrição": "descrição detalhada",
    "descricao": "descrição detalhada",
    "description": "detailed description",
    "forma de pagamento": "método de pagamento (ex: crédito, débito, pix, dinheiro)",
    "forma_pagamento": "método de pagamento (ex: crédito, débito, pix, dinheiro)",
    "payment method": "payment method (ex: credit, debit, pix, cash)",
    "pagamento": "método de pagamento (ex: crédito, débito, pix, dinheiro)",
    "observações": "informações adicionais relevantes",
    "observacoes": "informações adicionais relevantes",
    "quem fez": "nome da pessoa que fez a compra",
    "quem_fez": "nome da pessoa que fez a compra",
}

_DEFAULT_COLUMN_HINT = "extraia o valor correspondente ou null se não houver informação na mensagem"


_QUERY_STARTERS = (
    "quanto", "quanta", "quantos", "quantas", "qual", "quais", "como",
    "resumo", "resuma", "total", "totais", "média", "media", "balanço",
    "balanco", "saldo",
)


def _build_combined_prompt(text: str, headers: list[str], today: str) -> str:
    cols = "\n".join(
        f'- "{h}": {_COLUMN_HINTS.get(h.lower().strip(), _DEFAULT_COLUMN_HINT)}'
        for h in headers
    )
    return (
        "Analise a mensagem de um app de finanças pessoais e responda SOMENTE com JSON.\n"
        f"Data de hoje: {today}\n"
        "\n"
        "Primeiro decida a intenção:\n"
        '- "record" = registrar um gasto, receita ou transação financeira.\n'
        '- "query" = perguntar sobre gastos, pedir resumo, análise ou consulta.\n'
        "\n"
        f"A planilha do usuário tem estes cabeçalhos: {headers}\n"
        "Instruções para cada coluna (usadas SOMENTE se a intenção for \"record\"):\n"
        f"{cols}\n"
        "\n"
        'Retorne SOMENTE um JSON no formato: {"intent": "record" ou "query", "data": {...} ou null}\n'
        "\n"
        "IMPORTANTE:\n"
        '- Se intent for "record", "data" deve ter chaves EXATAMENTE iguais aos cabeçalhos '
        f"acima. Para colunas de DATA use {today} se não mencionado. NÃO invente dados, "
        "use null para o que não foi informado.\n"
        '- Se intent for "query", "data" deve ser null.\n'
        "\n"
        f"Mensagem: {text}"
    )


QUERY_PROMPT = """Você é um assistente de finanças pessoais.

Responda à pergunta do usuário com base APENAS nos dados abaixo.
Se os dados não tiverem informação suficiente para responder, diga isso claramente.
Não invente valores nem assuma informações que não estão na planilha.

Planilha:
{sheet_data}

Pergunta: {text}"""


def _fast_classify(text: str) -> str | None:
    stripped = text.strip()
    if stripped.endswith("?"):
        return "query"
    first_word = stripped.split(" ", 1)[0].lower().strip("?!.,") if stripped else ""
    if first_word in _QUERY_STARTERS:
        return "query"
    return None


def _truncate(text: str, max_len: int = _MAX_TEXT_LENGTH) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


async def classify_and_parse(text: str, headers: list[str]) -> tuple[str, dict]:
    """Classify intent and, for records, extract fields in a single LLM call."""
    fast = _fast_classify(text)
    if fast == "query":
        return "query", {}

    today = date.today().isoformat()
    prompt = _build_combined_prompt(_truncate(text), headers, today)
    raw = await _llm(prompt, json_mode=True, max_tokens=250)
    result = json.loads(raw)

    intent = result.get("intent")
    if intent not in ("record", "query"):
        intent = "record"

    data = result.get("data") if intent == "record" else {}
    return intent, data if isinstance(data, dict) else {}


async def answer_query(text: str, sheet_data: str) -> str:
    return await _llm(
        QUERY_PROMPT.format(sheet_data=sheet_data, text=_truncate(text)),
        max_tokens=400,
    )
