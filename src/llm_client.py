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

    Анализируем все реплики пользователя, учитывая историю диалога.
    """
    user_messages = [
        str(m.get("content", ""))
        for m in messages
        if m.get("role") == "user"
    ]

    full_text = " ".join(user_messages).lower()

    city_id = None

    # Ищем последний город, который упомянул покупатель
    for message in reversed(user_messages):
        message_text = message.lower()

        if "таганрог" in message_text:
            city_id = "taganrog"
        elif "ростов" in message_text:
            city_id = "rostov-na-donu"
        elif "азов" in message_text:
            city_id = "azov"
        elif "москв" in message_text or "краснодар" in message_text:
            city_id = "UNKNOWN_CITY"

        if city_id is not None:
            break

    categories = []

    category_rules = [
        (
            "table",
            r"стол",
            r"(?:стол\w*\s+(?:не\s+нужн\w*|не\s+надо|не\s+требу\w*)|(?:не\s+нужн\w*|не\s+надо|не\s+требу\w*)\s+стол\w*|без\s+стол\w*)",
        ),
        (
            "chair",
            r"кресл|стул",
            r"(?:кресл|стул)\w*\s+(?:не\s+нужн\w*|не\s+надо|не\s+требу\w*)|(?:не\s+нужн\w*|не\s+надо|не\s+требу\w*)\s+(?:кресл|стул)\w*|без\s+(?:кресл|стул)\w*",
        ),
        (
            "lamp",
            r"ламп|светильник",
            r"(?:ламп|светильник)\w*\s+(?:не\s+нужн\w*|не\s+надо|не\s+требу\w*)|(?:не\s+нужн\w*|не\s+надо|не\s+требу\w*)\s+(?:ламп|светильник)\w*|без\s+(?:ламп|светильник)\w*",
        ),
    ]

    for message in user_messages:
        message_text = message.lower()

        for category, keyword_pattern, removal_pattern in category_rules:
            if re.search(removal_pattern, message_text):
                if category in categories:
                    categories.remove(category)

            elif re.search(keyword_pattern, message_text):
                if category not in categories:
                    categories.append(category)

    has_unsupported = any(w in full_text for w in ["шкаф", "диван", "монитор", "тумб"])

    budget_rub = None

    budget_matches = list(re.finditer(
        r"(\d[\d\s\u00a0\u202f]*)\s*(тыс(?:яч(?:а|и)?)?\.?|к\b|руб(?:лей|ля|ль)?\.?|₽)",
        full_text,
    ))

    m_budget = budget_matches[-1] if budget_matches else None

    if m_budget:
        val = int(re.sub(r"\D", "", m_budget.group(1)))
        unit = m_budget.group(2)

        if unit.startswith(("тыс", "к")):
            val *= 1000

        budget_rub = val

    table_min = None
    table_max = None

    width_unit = r"(?:см|сантиметр(?:а|ов)?|м|метр(?:а|ов)?)"

    cancel_width_patterns = [
        r"ограничени\w*.*ширин\w*.*(?:убрат\w*|снят\w*|отмен\w*)",
        r"(?:убрат\w*|снят\w*|отмен\w*).*ограничени\w*.*ширин\w*",
        r"ширин\w*.*(?:не\s+важн\w*|не\s+принципиальн\w*|не\s+имеет\s+значени\w*)",
        r"(?:подойдут|подойдет).*люб\w*\s+(?:ширин\w*|размер\w*)",
    ]

    for message in user_messages:
        message_text = message.lower()

        # Проверяем, не отменил ли покупатель ограничение
        if any(re.search(p, message_text) for p in cancel_width_patterns):
            table_min = None
            table_max = None
            continue

        # Максимальная ширина
        max_width_match = re.search(
            rf"(?:не\s+шире|не\s+более|до|максимум)\s*(\d+(?:[.,]\d+)?)\s*({width_unit})\b",
            message_text,
        )

        if max_width_match:
            value = float(max_width_match.group(1).replace(",", "."))
            unit = max_width_match.group(2)

            table_max = (
                int(round(value * 100))
                if unit == "м" or unit.startswith("метр")
                else int(round(value))
            )

        elif re.search(
            r"(?:не\s+шире|не\s+более|до|максимум)\s+(?:одного\s+)?метр(?:а|ов)?\b",
            message_text,
        ):
            table_max = 100

        # Минимальная ширина
        min_width_match = re.search(
            rf"(?:не\s+меньше|не\s+уже|от)\s*(\d+(?:[.,]\d+)?)\s*({width_unit})\b",
            message_text,
        )

        if min_width_match:
            value = float(min_width_match.group(1).replace(",", "."))
            unit = min_width_match.group(2)

            table_min = (
                int(round(value * 100))
                if unit == "м" or unit.startswith("метр")
                else int(round(value))
            )
    chair_adj = True if "регулировк" in full_text else None
    lamp_max = 3300 if "тепл" in full_text or "тёпл" in full_text else None

    return {
        "city_id": city_id,
        "budget_rub": budget_rub,
        "categories": categories,
        "has_unsupported_category": has_unsupported,
        "table_width": {"min": table_min, "max": table_max},
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