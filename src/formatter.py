from typing import Any, Dict, List

CATEGORY_LABELS_ACCUSATIVE = {
    "table": "стол",
    "chair": "кресло",
    "lamp": "лампу",
}


def build_clarify_questions(
    reqs: Dict[str, Any],
    valid_city_ids: set[str],
) -> List[Dict[str, str]]:
    questions: List[Dict[str, str]] = []

    categories = reqs.get("categories") or []
    if not categories or reqs.get("has_unsupported_category"):
        questions.append(
            {
                "field": "categories",
                "text": "Какие категории товаров вам нужны? Доступны: стол (table), кресло (chair) и лампа (lamp).",
            }
        )

    city_id = reqs.get("city_id")
    if not city_id or city_id == "UNKNOWN_CITY" or (valid_city_ids and city_id not in valid_city_ids):
        questions.append(
            {
                "field": "city_id",
                "text": "В каком городе вы планируете забрать товары? Доступны: Таганрог, Ростов-на-Дону и Азов.",
            }
        )

    budget_rub = reqs.get("budget_rub")
    if budget_rub is None or isinstance(budget_rub, bool) or not isinstance(budget_rub, int) or budget_rub < 0:
        questions.append(
            {
                "field": "budget_rub",
                "text": "Какой у вас максимальный общий бюджет на комплект в рублях?",
            }
        )

    return questions


def build_explanation(bundle: Dict[str, Any]) -> str:
    parts: List[str] = []
    for item in bundle["items"]:
        attrs = item.get("attributes") or {}
        cat = item.get("category")
        title = item.get("title", "Товар")
        price = item["price_rub"]
        details = [f"{price} ₽"]

        if cat == "table" and "width_cm" in attrs:
            details.append(f"ширина {attrs['width_cm']} см")
        elif cat == "chair" and "adjustable_height" in attrs:
            details.append("с регулировкой высоты" if attrs["adjustable_height"] else "без регулировки высоты")
        elif cat == "lamp" and "color_temperature_k" in attrs:
            details.append(f"{attrs['color_temperature_k']} K")

        parts.append(f"{title} ({', '.join(details)})")

    return f"Комплект в рамках бюджета: {'; '.join(parts)}. Итого: {bundle['total_rub']} ₽."


def format_ok_response(bundles: List[Dict[str, Any]]) -> Dict[str, Any]:
    options = []
    for bundle in bundles:
        options.append(
            {
                "listing_ids": [item["id"] for item in bundle["items"]],
                "total_rub": bundle["total_rub"],
                "explanation": build_explanation(bundle),
            }
        )
    return {
        "status": "ok",
        "options": options,
    }


def format_no_match_missing_items(empty_categories: List[str]) -> Dict[str, Any]:
    missing_str = ", ".join(CATEGORY_LABELS_ACCUSATIVE.get(c, c) for c in empty_categories)
    return {
        "status": "no_match",
        "message": (
            f"В выбранном городе не найдены подходящие предложения для категории: {missing_str} "
            "с указанными параметрами. Попробуйте смягчить требования или выбрать другой город."
        ),
    }


def format_no_match_budget(min_possible: int, budget_rub: int) -> Dict[str, Any]:
    return {
        "status": "no_match",
        "message": (
            f"Подходящие товары есть в наличии, но минимальная стоимость полного комплекта составляет "
            f"{min_possible} ₽, что превышает ваш бюджет ({budget_rub} ₽). "
            "Попробуйте увеличить бюджет или сократить список категорий."
        ),
    }
