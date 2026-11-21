import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List

from src.config import err_exit, get_llm_config, log


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


# Общий бюджет времени на весь запуск run: контракт даёт 120 с, оставляем запас.
_START = time.monotonic()
_TOTAL_DEADLINE_S = 100.0
_MAX_ATTEMPTS = 4
_RETRY_HTTP = (429, 502, 503)


def _time_left() -> float:
    return _TOTAL_DEADLINE_S - (time.monotonic() - _START)


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

    last_err = "unknown error"
    for attempt in range(_MAX_ATTEMPTS):
        remaining = _time_left()
        if remaining < 5:
            err_exit(f"LLM deadline exceeded. Last error: {last_err}")

        wait_s = 2 ** attempt  # 1, 2, 4 секунды между попытками
        req = urllib.request.Request(cfg["url"], data=payload_bytes, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=min(cfg["timeout"], remaining)) as resp:
                raw_body = resp.read().decode("utf-8")
            data = json.loads(raw_body)
            choices = data.get("choices") or []
            if not choices:
                raise ValueError("LLM response has empty 'choices'")
            choice = choices[0]
            if choice.get("finish_reason") != "stop":
                raise ValueError(f"finish_reason is not 'stop': {choice.get('finish_reason')}")
            return json.loads(choice["message"]["content"])
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            last_err = f"LLM API HTTP {e.code}: {err_body}"
            if e.code not in _RETRY_HTTP:
                err_exit(last_err)
            retry_after = e.headers.get("Retry-After") if e.headers else None
            if retry_after and retry_after.isdigit():
                wait_s = min(int(retry_after), 20)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last_err = f"LLM API request failed: {e}"
        except (ValueError, KeyError, TypeError) as e:
            # Невалидный JSON или обрезанная генерация: одна-две повторные попытки допустимы.
            last_err = f"Failed to parse LLM output: {e}"

        log(f"LLM attempt {attempt + 1}/{_MAX_ATTEMPTS} failed: {last_err}")
        if attempt < _MAX_ATTEMPTS - 1:
            if _time_left() < wait_s + 5:
                break
            time.sleep(wait_s)

    err_exit(last_err)
