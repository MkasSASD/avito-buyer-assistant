import json
from typing import Any, Dict, List

from src.llm_client import call_llm_structured

REQUIREMENTS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "city_id": {
            "type": ["string", "null"],
            "description": "ID города из справочника, 'UNKNOWN_CITY' если назван город не из списка, или null если город не указан.",
        },
        "budget_rub": {
            "type": ["integer", "null"],
            "description": "Максимальный бюджет на весь комплект в рублях (неотрицательное целое число), либо null.",
        },
        "categories": {
            "type": "array",
            "items": {"type": "string", "enum": ["table", "chair", "lamp"]},
            "description": "Актуальный список поддерживаемых категорий, которые нужны пользователю.",
        },
        "has_unsupported_category": {
            "type": "boolean",
            "description": "true, если в актуальном запросе пользователь просит хотя бы одну неподдерживаемую категорию (например, шкаф, диван, ковёр, монитор).",
        },
        "table_width": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "min": {"type": ["integer", "null"]},
                "max": {"type": ["integer", "null"]},
            },
            "required": ["min", "max"],
        },
        "chair_adjustable_height": {
            "type": ["boolean", "null"],
            "description": "true — нужна регулировка высоты, false — строго без неё, null — не важно.",
        },
        "lamp_color_temp": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "min": {"type": ["integer", "null"]},
                "max": {"type": ["integer", "null"]},
            },
            "required": ["min", "max"],
        },
    },
    "required": [
        "city_id",
        "budget_rub",
        "categories",
        "has_unsupported_category",
        "table_width",
        "chair_adjustable_height",
        "lamp_color_temp",
    ],
}


def extract_requirements(
    messages: List[Dict[str, str]],
    cities_data: List[Dict[str, Any]],
) -> Dict[str, Any]:
    cities_json = json.dumps(cities_data, ensure_ascii=False)

    system_prompt = f"""Ты — модуль извлечения структурированных параметров для сервиса подбора мебели и освещения.
Анализируй ВЕСЬ диалог целиком (учитывая уточнения и исправления в последних репликах пользователя).

Справочник доступных городов:
{cities_json}

Правила извлечения:
1. city_id:
   - Сопоставь город пользователя (включая склонения и опечатки: «в Таганроге» -> taganrog, «Ростов» -> rostov-na-donu, «в Азове» -> azov) со справочником и верни его `id`.
   - Если пользователь назвал город, которого НЕТ в справочнике (например, Москва, Краснодар), верни `"UNKNOWN_CITY"`.
   - Если город ещё не назывался, верни `null`.

2. budget_rub:
   - Извлеки максимальный общий бюджет в рублях (целое число).
   - Переводи сокращения: «15к» / «15 тыс» -> 15000.
   - Если бюджет не указан или указан некорректно (отрицательный), верни `null`.

3. categories и has_unsupported_category:
   - Поддерживаются ТОЛЬКО три категории: `"table"` (стол), `"chair"` (кресло/стул), `"lamp"` (лампа/светильник).
   - Учитывай эволюцию диалога: если сначала пользователь просил шкаф, а после уточнения ассистента написал «нужен только стол», то `categories: ["table"]` и `has_unsupported_category: false`.
   - Если в актуальном запросе пользователя присутствует хотя бы одна неподдерживаемая категория (шкаф, тумба, диван, монитор и т.д.), поставь `has_unsupported_category: true`.

4. Характеристики товаров:
   - `table_width` (ширина стола в см): «от 120» / «не меньше 120» -> `min: 120`; «до 140» / «не шире 140» -> `max: 140`; «ровно 120» -> `min: 120, max: 120`.
   - `chair_adjustable_height`: «с регулировкой высоты» / «газлифт» -> `true`; «без регулировки» -> `false`; иначе `null`.
   - `lamp_color_temp` (цветовая температура в Кельвинах): «тёплый свет» -> `max: 3300`; «нейтральный / дневной» -> `min: 3500, max: 4500`; «холодный свет» -> `min: 5000`; либо точные числовые границы в K.

Не пиши пояснений, верни строго JSON по заданной схеме."""

    llm_messages: List[Dict[str, str]] = [{"role": "system", "content": system_prompt}]
    for m in messages:
        role = m.get("role", "user")
        text = m.get("text") if "text" in m else m.get("content", "")
        llm_messages.append({"role": role, "content": str(text)})

    return call_llm_structured(
        messages=llm_messages,
        schema_name="buyer_requirements",
        json_schema=REQUIREMENTS_SCHEMA,
        max_tokens=1000,
    )