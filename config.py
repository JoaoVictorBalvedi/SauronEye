import os
from dotenv import load_dotenv
from functools import lru_cache

load_dotenv()


@lru_cache
def get_settings():
    telegram_api_url = os.environ.get(
        "TELEGRAM_API_URL", "https://api.telegram.org/bot"
    )
    telegram_proxy_url = os.environ.get("TELEGRAM_PROXY_URL") or os.environ.get("HTTPS_PROXY")
    return {
        "bot_token": os.environ["BOT_TOKEN"],
        "telegram_api_url": telegram_api_url.rstrip("/") + "/",
        "telegram_proxy_url": telegram_proxy_url,
        "ollama_url": os.environ.get("OLLAMA_URL", "http://localhost:11434"),
        "llm_model": os.environ.get("LLM_MODEL", "llama3.2"),
        "service_account_file": os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE"),
        "service_account_content": os.environ.get("GOOGLE_SERVICE_ACCOUNT"),
        "service_account_email": os.environ.get("SERVICE_ACCOUNT_EMAIL"),
    }
