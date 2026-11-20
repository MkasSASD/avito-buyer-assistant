import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List

from src.config import err_exit, get_llm_config


def _mock_llm_extract(messages: List[Dict[str, str]]) -> Dict[str, Any]:
    """Простая эвристика для локальной отладки без API-ключа.

    Смотрим ТОЛЬКО на последнюю реплику пользователя, чтобы имитировать
    обработку истории моделью (явное изменение условия заменяет старое).
    """
    last_user = next(
        (m["content"] for m in reversed(messages) if m.get("role") == "user"),
        "",
    )
    full_text = last_user.lower()

    city_id = None
    if "таганрог" in full_text:
        city_id = "taganrog"
    elif "ростов" in full_text:
        city_id = "rostov-na-donu"
    elif "азов" in full_text:
        city_id = "azov"
    elif "москв" in full_text or "краснодар" in full_text:
        city_id = "UNKNOWN_CITY"

    categories = []
    if "стол" in full_text:
        categories.append("table")
    if "кресл" in full_text or "стул" in full_text:
        categories.append("chair")
    if "ламп" in full_text or "светильник" in full_text:
        categories.append("lamp")

    has_unsupported = any(w in full_text for w in ["шкаф", "диван", "монитор", "тумб"])

    budget_rub = None
    m_budget = re.search(r"(\d+)\s*(?:тыс|к|руб|₽)", full_text)
    if m_budget:
        val = int(m_budget.group(1))
        if "тыс" in m_budget.group(0) or "к" in m_budget.group(0):
            val *= 1000
        budget_rub = val

    table_min = 120 if "120" in full_text else None
    chair_adj = True if "регулировк" in full_text else None
    lamp_max = 3300 if "тепл" in full_text or "тёпл" in full_text else None

    return {
        "city_id": city_id,
        "budget_rub": budget_rub,
        "categories": categories,
        "has_unsupported_category": has_unsupported,
        "table_width": {"min": table_min, "max": None},
        "chair_adjustable_height": chair_adj,
        "lamp_color_temp": {"min": None, "max": lamp_max},
    }


def call_llm_structured(
    messages: List[Dict[str, str]],
    schema_name: str,
    json_schema: Dict[str, Any],
    max_tokens: int = 1000,
) -> Dict[str, Any]:
    if os.environ.get("LLM_API_KEY") == "mock":
        return _mock_llm_extract(messages)

    cfg = get_llm_config()

    payload = {
        "model": cfg["model"],
        "messages": messages,
        "temperature": 0.0,
        "max_tokens": max_tokens,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": schema_name,
                "strict": True,
                "schema": json_schema,
            },
        },
    }
    payload_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {cfg['api_key']}",
        "Content-Type": "application/json",
        "User-Agent": cfg["user_agent"],
    }

    raw_body = None
    last_err: str = "unknown error"
    # До 3 попыток: retry только на 429 (лимит) и 503 (шлюз недоступен).
    for attempt in range(3):
        req = urllib.request.Request(cfg["url"], data=payload_bytes, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=cfg["timeout"]) as resp:
                raw_body = resp.read().decode("utf-8")
            break
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            last_err = f"LLM API HTTP {e.code}: {err_body}"
            if e.code in (429, 503) and attempt < 2:
                time.sleep(2 ** attempt)
                continue
            err_exit(last_err)
        except Exception as e:
            err_exit(f"LLM API request failed: {e}")

    if raw_body is None:
        err_exit(last_err)

    try:
        data = json.loads(raw_body)
        choices = data.get("choices") or []
        if not choices:
            err_exit("LLM response has empty 'choices'")
        choice = choices[0]
        if choice.get("finish_reason") != "stop":
            err_exit(f"LLM finish_reason is not 'stop': {choice.get('finish_reason')}")
        content = choice["message"]["content"]
        return json.loads(content)
    except SystemExit:
        raise
    except Exception as e:
        err_exit(f"Failed to parse LLM JSON output: {e}")