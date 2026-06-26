import json
import httpx
from config import get_settings


async def _llm(prompt: str, json_mode: bool = False) -> str:
    settings = get_settings()
    body = {
        "model": settings["llm_model"],
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }
    if json_mode:
        body["format"] = "json"
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{settings['ollama_url']}/api/chat", json=body, timeout=60
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"]


CLASSIFY_PROMPT = """Classifique a intenção da mensagem como "record" ou "query".

Exemplos de "record" (registrar gasto/receita):
- "comprei pão por 5 reais"
- "gasolina 50 reais no posto"
- "recebi 3000 de salário"
- "ifood 25 reais no débito"

Exemplos de "query" (pergunta/consulta):
- "quanto gastei esse mês?"
- "resumo dos gastos"
- "quanto foi de combustível em maio?"
- "total gasto na categoria casa"
- "como estão minhas finanças?"

Responda APENAS com {"intent": "record"} ou {"intent": "query"}.

Mensagem: {text}"""

RECORD_PROMPT = """Extraia os dados financeiros desta mensagem e retorne SOMENTE JSON válido com:
- "nome": nome do item ou descrição do que foi comprado
- "valor": valor numérico positivo
- "data": data no formato YYYY-MM-DD (se não mencionar, use hoje)
- "categoria": um de [Dia a Dia, Combustível, Casa, Máquinas, Insumos Plantas, Investimentos, Funcionários, Insumos Gado, Compra de Gado, Serviços]
- "quem_fez": quem fez a compra (inferir do contexto)
- "forma_pagamento": um de [Cartão de Crédito, Cartão de Débito, Pix, Dinheiro]
- "observacoes": observações adicionais

Mensagem: {text}"""

QUERY_PROMPT = """Você é um assistente de finanças pessoais. Abaixo estão os dados da planilha do usuário.
Responda à pergunta dele de forma clara e objetiva com base nos dados.

Planilha:
{sheet_data}

Pergunta: {text}"""


async def classify_intent(text: str) -> str:
    if text.strip().endswith("?"):
        return "query"
    raw = await _llm(CLASSIFY_PROMPT.format(text=text), json_mode=True)
    print(f"[CLASSIFY RAW] {raw}")
    try:
        result = json.loads(raw).get("intent", "")
        print(f"[CLASSIFY] {result}")
        if result in ("record", "query"):
            return result
    except json.JSONDecodeError:
        pass
    print(f"[CLASSIFY] Falling back to 'record'")
    return "record"


async def parse_message(text: str) -> dict:
    raw = await _llm(RECORD_PROMPT.format(text=text), json_mode=True)
    print(f"[PARSE RAW] {raw}")
    parsed = json.loads(raw)
    valor = parsed.get("valor")
    parsed["valor"] = abs(float(valor)) if valor is not None else 0
    return parsed


async def answer_query(text: str, sheet_data: str) -> str:
    return await _llm(QUERY_PROMPT.format(sheet_data=sheet_data, text=text))
