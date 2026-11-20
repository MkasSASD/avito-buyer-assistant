import argparse
import json
import os
import sys
from typing import Any, Dict, List

from src.config import err_exit, log
from src.extractor import extract_requirements
from src.formatter import (
    build_clarify_questions,
    format_no_match_budget,
    format_no_match_missing_items,
    format_ok_response,
)
from src.matcher import filter_items_by_category, find_bundles


def load_json_file(path: str) -> Any:
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception as e:
        err_exit(f"Failed to load JSON from {path}: {e}")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Buyer Assistant")
    parser.add_argument(
        "--catalog",
        default="data/catalog.json",
        help="Path to catalog.json",
    )

    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    cities_path = os.path.join(script_dir, "data", "cities.json")
    cities_data = load_json_file(cities_path) if os.path.exists(cities_path) else []
    catalog = load_json_file(args.catalog)

    try:
        raw_stdin = sys.stdin.buffer.read().decode("utf-8-sig")
        request_data = json.loads(raw_stdin)
    except Exception as e:
        err_exit(f"Invalid JSON on stdin: {e}")

    messages = request_data.get("messages")
    if not isinstance(messages, list) or not messages:
        err_exit("Empty or invalid 'messages' array in input JSON.")

    reqs = extract_requirements(messages, cities_data)
    log(f"Extracted requirements: {json.dumps(reqs, ensure_ascii=False)}")

    valid_city_ids = {c["id"] for c in cities_data if isinstance(c, dict) and "id" in c}
    questions = build_clarify_questions(reqs, valid_city_ids)

    if questions:
        print(json.dumps({"status": "clarify", "questions": questions}, ensure_ascii=False))
        return

    city_id: str = reqs["city_id"]
    budget_rub: int = reqs["budget_rub"]
    categories: List[str] = list(dict.fromkeys(reqs["categories"]))

    items_by_cat: Dict[str, List[Dict[str, Any]]] = {}
    empty_cats: List[str] = []

    for cat in categories:
        matched = filter_items_by_category(catalog, city_id, cat, reqs)
        items_by_cat[cat] = matched
        if not matched:
            empty_cats.append(cat)

    if empty_cats:
        print(json.dumps(format_no_match_missing_items(empty_cats), ensure_ascii=False))
        return

    bundles = find_bundles(items_by_cat, categories, budget_rub, max_options=3)
    if not bundles:
        min_possible = sum(items_by_cat[cat][0]["price_rub"] for cat in categories)
        print(json.dumps(format_no_match_budget(min_possible, budget_rub), ensure_ascii=False))
        return

    print(json.dumps(format_ok_response(bundles), ensure_ascii=False))


if __name__ == "__main__":
    main()
