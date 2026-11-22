#!/usr/bin/env python3
"""Прогон граничных сценариев через ./run с проверкой ответов по каталогу.

Запуск из корня репозитория (в Git Bash, с заданными LLM_* переменными):
    python3 edge_check.py
    python3 edge_check.py --catalog data/catalog.json

Скрипт ничего не меняет в проекте. На каждый сценарий делается один вызов модели.
"""
import argparse
import json
import subprocess
import sys
import time

U, A = "user", "assistant"

# expect: допустимые статусы; fields: ожидаемые поля clarify (точное множество);
# для ok проверяются город, категории, бюджет и ограничения по каталогу.
CASES = [
    {"name": "стол не шире метра (включает 100)", "expect": {"ok"},
     "msgs": [(U, "Нужен стол не шире метра. Таганрог, бюджет 50000 рублей.")],
     "city": "таганрог", "cats": ["table"], "budget": 50000, "width": (None, 100)},
    {"name": "стол шире 100 см (строго, от 101)", "expect": {"ok"},
     "msgs": [(U, "Стол шире 100 см, город Таганрог, до 50 тысяч.")],
     "city": "таганрог", "cats": ["table"], "budget": 50000, "width": (101, None)},
    {"name": "стол не более 1,2 метра (метры в см)", "expect": {"ok"},
     "msgs": [(U, "Стол шириной не более 1,2 метра, Таганрог, бюджет 50000.")],
     "city": "таганрог", "cats": ["table"], "budget": 50000, "width": (None, 120)},
    {"name": "лампа ниже 4000 K (строго, до 3999)", "expect": {"ok"},
     "msgs": [(U, "Лампа с цветовой температурой ниже 4000 K, Таганрог, бюджет 20000.")],
     "city": "таганрог", "cats": ["lamp"], "budget": 20000, "temp": (None, 3999)},
    {"name": "кресло без регулировки высоты (false)", "expect": {"ok"},
     "msgs": [(U, "Кресло без регулировки высоты, Таганрог, до 30000 рублей.")],
     "city": "таганрог", "cats": ["chair"], "budget": 30000, "adj": False},
    {"name": "комплект стол+кресло+лампа с ограничениями", "expect": {"ok"},
     "msgs": [(U, "Стол не шире метра, кресло с регулировкой высоты и лампа не выше 4500 K. "
                  "Таганрог. До 40 000 ₽ за всё.")],
     "city": "таганрог", "cats": ["table", "chair", "lamp"], "budget": 40000,
     "width": (None, 100), "adj": True, "temp": (None, 4500)},
    {"name": "нет города и бюджета -> clarify обоих", "expect": {"clarify"},
     "msgs": [(U, "Нужен стол и лампа.")], "fields": {"city_id", "budget_rub"}},
    {"name": "нет только бюджета -> clarify budget", "expect": {"clarify"},
     "msgs": [(U, "Стол и лампа, Таганрог.")], "fields": {"budget_rub"}},
    {"name": "неподдерживаемая категория -> clarify categories", "expect": {"clarify"},
     "msgs": [(U, "Нужен шкаф, Таганрог, бюджет 30000.")], "fields": {"categories"}},
    {"name": "город не из справочника -> clarify city_id", "expect": {"clarify"},
     "msgs": [(U, "Стол в Москве, бюджет 30000.")], "fields": {"city_id"}},
    {"name": "история: бюджет заменён на 15000", "expect": {"ok"},
     "msgs": [(U, "Стол и лампа в Таганроге, до 20 тысяч."),
              (A, "Могу предложить комплект. Подойдёт?"),
              (U, "Нет, давайте уложимся в 15 тысяч.")],
     "city": "таганрог", "cats": ["table", "lamp"], "budget": 15000},
    {"name": "короткий ответ «15 тысяч» на вопрос о бюджете", "expect": {"ok"},
     "msgs": [(U, "Стол и лампа в Таганроге."),
              (A, "Какой у вас максимальный общий бюджет в рублях?"),
              (U, "15 тысяч")],
     "city": "таганрог", "cats": ["table", "lamp"], "budget": 15000},
    {"name": "бюджет 0 -> no_match (цены больше 0)", "expect": {"no_match"},
     "msgs": [(U, "Стол в Таганроге, бюджет 0 рублей.")]},
]


def find_city_id(cities, prefix):
    for c in cities:
        if isinstance(c, dict) and any(
            isinstance(v, str) and v.lower().startswith(prefix) for v in c.values()
        ):
            return c.get("id")
    return None


def in_range(value, bounds):
    lo, hi = bounds
    if not isinstance(value, int) or isinstance(value, bool):
        return False
    return (lo is None or value >= lo) and (hi is None or value <= hi)


def check_ok(resp, case, catalog, city_id):
    problems = []
    options = resp.get("options")
    if not isinstance(options, list) or not 1 <= len(options) <= 3:
        return ["options должен быть списком из 1-3 вариантов"]
    by_id = {x["id"]: x for x in catalog}
    seen = set()
    for n, opt in enumerate(options, 1):
        ids = opt.get("listing_ids", [])
        tag = f"вариант {n}"
        if len(set(ids)) != len(ids):
            problems.append(f"{tag}: повторяющиеся ID")
        if any(i not in by_id for i in ids):
            problems.append(f"{tag}: ID нет в каталоге")
            continue
        items = [by_id[i] for i in ids]
        if sorted(x["category"] for x in items) != sorted(case["cats"]):
            problems.append(f"{tag}: категории {[x['category'] for x in items]} != {case['cats']}")
        if city_id and any(x["city_id"] != city_id for x in items):
            problems.append(f"{tag}: есть товар не из города {city_id}")
        total = sum(x["price_rub"] for x in items)
        if opt.get("total_rub") != total:
            problems.append(f"{tag}: total_rub {opt.get('total_rub')} != сумма {total}")
        if total > case["budget"]:
            problems.append(f"{tag}: {total} превышает бюджет {case['budget']}")
        if not str(opt.get("explanation", "")).strip():
            problems.append(f"{tag}: пустое объяснение")
        for x in items:
            attrs = x.get("attributes", {})
            if x["category"] == "table" and "width" in case and not in_range(attrs.get("width_cm"), case["width"]):
                problems.append(f"{tag}: стол {x['id']} width_cm={attrs.get('width_cm')} вне {case['width']}")
            if x["category"] == "lamp" and "temp" in case and not in_range(attrs.get("color_temperature_k"), case["temp"]):
                problems.append(f"{tag}: лампа {x['id']} color_temperature_k={attrs.get('color_temperature_k')} вне {case['temp']}")
            if x["category"] == "chair" and "adj" in case and attrs.get("adjustable_height") is not case["adj"]:
                problems.append(f"{tag}: кресло {x['id']} adjustable_height={attrs.get('adjustable_height')}")
        key = tuple(sorted(ids))
        if key in seen:
            problems.append(f"{tag}: состав совпадает с другим вариантом")
        seen.add(key)
    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", default="data/catalog.json")
    args = ap.parse_args()

    with open(args.catalog, encoding="utf-8-sig") as f:
        catalog = json.load(f)
    with open("data/cities.json", encoding="utf-8-sig") as f:
        cities = json.load(f)

    failed = 0
    for case in CASES:
        request = {"messages": [{"role": r, "text": t} for r, t in case["msgs"]]}
        t0 = time.time()
        try:
            p = subprocess.run(
                ["bash", "./run", "--catalog", args.catalog],
                input=json.dumps(request, ensure_ascii=False).encode("utf-8"),
                capture_output=True, timeout=130,
            )
        except subprocess.TimeoutExpired:
            print(f"FAIL  {case['name']}: таймаут 130 с")
            failed += 1
            continue
        dt = time.time() - t0
        problems = []
        status = "?"
        if p.returncode != 0:
            problems.append(f"код выхода {p.returncode}: {p.stderr.decode('utf-8', 'replace')[-300:]}")
        else:
            try:
                resp = json.loads(p.stdout.decode("utf-8"))
                status = resp.get("status")
            except Exception as e:
                resp = {}
                problems.append(f"stdout не JSON: {e}")
            if resp:
                if status not in case["expect"]:
                    problems.append(f"статус {status}, ожидался один из {sorted(case['expect'])}")
                elif status == "clarify" and "fields" in case:
                    got = {q.get("field") for q in resp.get("questions", [])}
                    if got != case["fields"]:
                        problems.append(f"поля clarify {sorted(got)} != {sorted(case['fields'])}")
                elif status == "ok":
                    city_id = find_city_id(cities, case["city"]) if "city" in case else None
                    if "city" in case and not city_id:
                        print(f"      (город «{case['city']}» не найден в cities.json, проверка города пропущена)")
                    problems += check_ok(resp, case, catalog, city_id)
        mark = "FAIL" if problems else "ok  "
        failed += bool(problems)
        print(f"{mark}  {case['name']}  [{status}, {dt:.1f} с]")
        for pr in problems:
            print(f"        - {pr}")
        time.sleep(1)

    print(f"\nИтого: {len(CASES) - failed} из {len(CASES)} без замечаний.")
    print("Ожидания рассчитаны на тестовый каталог из 111 объявлений (города taganrog, rostov-na-donu, azov).")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
