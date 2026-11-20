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
    # Модель строго из LLM_API.md. Дефолт совпадает с контрактом.
    model = (os.environ.get("LLM_MODEL") or "google/gemma-4-31B-it").strip()
    user_agent = (os.environ.get("LLM_USER_AGENT") or "hackathon-buyer-assistant/1.0").strip()

    if not base_url or not api_key:
        err_exit("LLM_BASE_URL or LLM_API_KEY environment variables are missing.")

    return {
        "url": f"{base_url}/chat/completions",
        "api_key": api_key,
        "model": model,
        "user_agent": user_agent,
        # По LLM_API.md до 90 с на один вызов, до 120 с на run целиком.
        "timeout": 90,
    }