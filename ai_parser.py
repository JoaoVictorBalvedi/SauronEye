import json
from datetime import date

import httpx
from config import get_settings

_MAX_TEXT_LENGTH = 500
_MAX_SHEET_ROWS = 30

_client = httpx.AsyncClient(timeout=httpx.Timeout(60))


async def close_llm():
    await _client.aclose()


async def _llm(prompt: str, json_mode: bool = False) -> str:
    settings = get_settings()
    body = {
        "model": settings["llm_model"],
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
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


def _build_record_prompt(text: str, headers: list[str], today: str) -> str:
    cols = "\n".join(
        f'- "{h}": {_COLUMN_HINTS.get(h.lower().strip(), _DEFAULT_COLUMN_HINT)}'
        for h in headers
    )
    return (
        f"Extraia os dados financeiros desta mensagem e retorne SOMENTE JSON.\n"
        f"Data de hoje: {today}\n"
        f"\n"
        f"A planilha do usuário tem estes cabeçalhos: {headers}\n"
        f"\n"
        f"Instruções para cada coluna:\n"
        f"{cols}\n"
        f"\n"
        f"As chaves do JSON devem ser EXATAMENTE os nomes das colunas acima.\n"
        f"\n"
        f"IMPORTANTE:\n"
        f"- Para colunas de DATA, use {today} se não mencionado na mensagem.\n"
        f"- NÃO invente dados. Use null para o que não foi informado.\n"
        f"\n"
        f"Mensagem: {text}"
    )


CLASSIFY_PROMPT = """Classifique a intenção da mensagem como "record" ou "query".

"record" = registrar um gasto, receita ou transação financeira.
"query" = perguntar sobre gastos, pedir resumo, análise ou consulta.

Exemplos de "record":
- "comprei pão por 5 reais"
- "gasolina 50 reais no posto"
- "recebi 3000 de salário"
- "ifood 25 reais no débito"
- "paguei a conta de luz 180"

Exemplos de "query":
- "quanto gastei esse mês?"
- "resumo dos gastos"
- "quanto foi de combustível em maio?"
- "total gasto na categoria casa"
- "como estão minhas finanças?"

Responda APENAS com {"intent": "record"} ou {"intent": "query"}.

Mensagem: {text}"""

QUERY_PROMPT = """Você é um assistente de finanças pessoais.

Responda à pergunta do usuário com base APENAS nos dados abaixo.
Se os dados não tiverem informação suficiente para responder, diga isso claramente.
Não invente valores nem assuma informações que não estão na planilha.

Planilha:
{sheet_data}

Pergunta: {text}"""

def _fast_classify(text: str) -> str | None:
    if text.strip().endswith("?"):
        return "query"
    return None


def _truncate(text: str, max_len: int = _MAX_TEXT_LENGTH) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


def _limit_rows(data: str, max_rows: int = _MAX_SHEET_ROWS) -> str:
    lines = data.strip().split("\n")
    if len(lines) <= max_rows + 1:
        return data
    header = lines[0]
    body = lines[1:]
    return header + "\n" + "\n".join(body[-max_rows:])


async def classify_intent(text: str) -> str:
    fast = _fast_classify(text)
    if fast:
        return fast

    raw = await _llm(CLASSIFY_PROMPT.format(text=_truncate(text)), json_mode=True)
    try:
        result = json.loads(raw).get("intent", "")
        if result in ("record", "query"):
            return result
    except json.JSONDecodeError:
        pass
    return "record"


async def parse_message(text: str, headers: list[str]) -> dict:
    today = date.today().isoformat()
    prompt = _build_record_prompt(_truncate(text), headers, today)
    raw = await _llm(prompt, json_mode=True)
    return json.loads(raw)


async def answer_query(text: str, sheet_data: str) -> str:
    return await _llm(
        QUERY_PROMPT.format(sheet_data=_limit_rows(sheet_data), text=_truncate(text))
    )
