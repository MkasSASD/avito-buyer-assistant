import os
import sys
from typing import NoReturn


def log(msg: str) -> None:
    print(f"[INFO] {msg}", file=sys.stderr, flush=True)


def err_exit(msg: str, code: int = 1) -> NoReturn:
    print(f"[ERROR] {msg}", file=sys.stderr, flush=True)
    sys.exit(code)


def get_llm_config() -> dict:
    base_url = (os.environ.get("LLM_BASE_URL") or "").strip().rstrip("/")
    api_key = (os.environ.get("LLM_API_KEY") or "").strip()
    model = (os.environ.get("LLM_MODEL") or "google/gemma-4-31B-it").strip()
    user_agent = (os.environ.get("LLM_USER_AGENT") or "hackathon-buyer-assistant/1.0").strip()

    if not base_url or not api_key:
        err_exit("LLM_BASE_URL or LLM_API_KEY environment variables are missing.")

    # Защита от ошибки 'latin-1' codec can't encode (кириллица в HTTP-заголовках)
    if not user_agent.isascii() or " " in user_agent:
        log("WARNING: LLM_USER_AGENT contains non-ASCII characters or spaces. Falling back to default.")
        user_agent = "hackathon-buyer-assistant/1.0"

    if not api_key.isascii():
        err_exit("LLM_API_KEY contains non-ASCII characters. Please check your environment variables.")

    return {
        "url": f"{base_url}/chat/completions",
        "api_key": api_key,
        "model": model,
        "user_agent": user_agent,
        "timeout": 90,
    }