import itertools
from typing import Any, Dict, List, Optional


def check_numeric_constraint(value: Any, constraint: Dict[str, Optional[int]]) -> bool:
    min_val = constraint.get("min")
    max_val = constraint.get("max")
    if min_val is None and max_val is None:
        return True
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    if min_val is not None and value < min_val:
        return False
    if max_val is not None and value > max_val:
        return False
    return True


def filter_items_by_category(
    catalog: List[Dict[str, Any]],
    city_id: str,
    category: str,
    reqs: Dict[str, Any],
) -> List[Dict[str, Any]]:
    matched: List[Dict[str, Any]] = []

    for item in catalog:
        if item.get("city_id") != city_id or item.get("category") != category:
            continue

        price = item.get("price_rub")
        # Контракт: price_rub — целое > 0.
        if not isinstance(price, int) or isinstance(price, bool) or price <= 0:
            continue

        attrs = item.get("attributes") or {}

        if category == "table":
            if not check_numeric_constraint(attrs.get("width_cm"), reqs["table_width"]):
                continue
        elif category == "chair":
            adj_req = reqs.get("chair_adjustable_height")
            if adj_req is not None:
                if not isinstance(attrs.get("adjustable_height"), bool):
                    continue
                if attrs["adjustable_height"] is not adj_req:
                    continue
        elif category == "lamp":
            if not check_numeric_constraint(attrs.get("color_temperature_k"), reqs["lamp_color_temp"]):
                continue

        matched.append(item)

    matched.sort(key=lambda x: (x["price_rub"], str(x.get("id", ""))))
    return matched


def find_bundles(
    items_by_cat: Dict[str, List[Dict[str, Any]]],
    categories: List[str],
    budget_rub: int,
    max_options: int = 3,
) -> List[Dict[str, Any]]:
    # Ограничиваем пул самыми дешёвыми позициями каждой категории
    pools = [items_by_cat[cat][:40] for cat in categories]
    valid_bundles: List[Dict[str, Any]] = []

    for combo in itertools.product(*pools):
        total = sum(item["price_rub"] for item in combo)
        if total <= budget_rub:
            valid_bundles.append({"items": list(combo), "total_rub": total})

    valid_bundles.sort(key=lambda b: b["total_rub"])

    if len(valid_bundles) <= max_options:
        return valid_bundles

    candidate_indices = [0, len(valid_bundles) // 2, len(valid_bundles) - 1]
    seen_keys = set()
    selected: List[Dict[str, Any]] = []

    for idx in candidate_indices:
        bundle = valid_bundles[idx]
        key = tuple(sorted(str(item["id"]) for item in bundle["items"]))
        if key not in seen_keys:
            seen_keys.add(key)
            selected.append(bundle)

    return selected