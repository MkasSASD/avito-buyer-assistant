#!/usr/bin/env python3
"""Консольная демонстрация помощника покупателя.

Это только оболочка для показа: каждая реплика отправляется в main.py так же,
как это делает проверяющий (весь диалог в JSON), а ответ печатается читаемо.
Для подбора и вопросов используется настоящая модель через LLM_* переменные.

Запуск из корня репозитория:
    python3 demo.py
Если в Git Bash ввод не работает, запустите:  winpty python demo.py
"""
import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))

# Быстрые фразы: введите цифру вместо текста.
PRESETS = {
    "1": "Нужен стол не шире метра, кресло с регулировкой высоты и лампа. Таганрог, до 15 000 рублей.",
    "2": "Хочу стол и лампу.",
    "3": "Таганрог, бюджет 15 тысяч.",
    "4": "Нет, давайте уложимся в 5 тысяч.",
    "5": "Стол и лампа в Таганроге, бюджет 100 рублей.",
}

LABELS = {"table": "Стол", "chair": "Кресло", "lamp": "Лампа"}
USE_COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
if USE_COLOR and os.name == "nt":
    os.system("")  # включает ANSI-цвета в консоли Windows


def paint(text, code):
    return f"\033[{code}m{text}\033[0m" if USE_COLOR else text


def money(value):
    return f"{value:,}".replace(",", " ") + " ₽"


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def describe_item(item):
    a = item.get("attributes") or {}
    bits = []
    if item.get("category") == "table" and is_int(a.get("width_cm")):
        bits.append(f"ширина {a['width_cm']} см")
    if item.get("category") == "chair" and isinstance(a.get("adjustable_height"), bool):
        bits.append("регулировка высоты есть" if a["adjustable_height"] else "без регулировки высоты")
    if item.get("category") == "lamp" and is_int(a.get("color_temperature_k")):
        bits.append(f"{a['color_temperature_k']} K")
    title = " ".join(str(item.get("title", "")).split())[:50]
    extra = f" ({', '.join(bits)})" if bits else ""
    return f"{LABELS.get(item.get('category'), 'Товар')}: {title}{extra} — {money(item['price_rub'])}"


def understood(reqs):
    """Короткая строка о том, что модель поняла из диалога."""
    parts = []
    if reqs.get("city_id"):
        parts.append(f"город: {reqs['city_id']}")
    if reqs.get("budget_rub") is not None:
        parts.append(f"бюджет: {money(reqs['budget_rub'])}")
    if reqs.get("categories"):
        parts.append("нужно: " + ", ".join(LABELS.get(c, c).lower() for c in reqs["categories"]))
    w = reqs.get("table_width") or {}
    if w.get("min") is not None or w.get("max") is not None:
        parts.append(f"ширина стола: {w.get('min') or '…'}–{w.get('max') or '…'} см")
    if reqs.get("chair_adjustable_height") is not None:
        parts.append("регулировка высоты: " + ("нужна" if reqs["chair_adjustable_height"] else "не нужна"))
    t = reqs.get("lamp_color_temp") or {}
    if t.get("min") is not None or t.get("max") is not None:
        parts.append(f"температура лампы: {t.get('min') or '…'}–{t.get('max') or '…'} K")
    return "; ".join(parts) if parts else "пока ничего определённого"


def call_main(messages, catalog_path):
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    request = json.dumps({"messages": messages}, ensure_ascii=False).encode("utf-8")
    return subprocess.run(
        [sys.executable, os.path.join(HERE, "main.py"), "--catalog", catalog_path],
        input=request, capture_output=True, timeout=130, env=env, cwd=HERE,
    )


def extract_requirements_from_log(stderr_text):
    for line in stderr_text.splitlines():
        if "Extracted requirements:" in line:
            try:
                return json.loads(line.split("Extracted requirements:", 1)[1])
            except Exception:
                return None
    return None


def render(resp, by_id, show_json):
    """Печатает ответ и возвращает текст для истории диалога (роль assistant)."""
    status = resp.get("status")
    if status == "clarify":
        texts = [q["text"] for q in resp.get("questions", [])]
        print(paint("Помощник уточняет:", "1;33"))
        for t in texts:
            print("  • " + t)
        history_text = " ".join(texts)
    elif status == "ok":
        print(paint("Помощник нашёл варианты:", "1;32"))
        for n, opt in enumerate(resp["options"], 1):
            print(paint(f"  Вариант {n} — итого {money(opt['total_rub'])}", "1"))
            for i in opt["listing_ids"]:
                item = by_id.get(i)
                print("    • " + (describe_item(item) if item else f"объявление {i}"))
        history_text = " ".join(o["explanation"] for o in resp["options"])
    elif status == "no_match":
        print(paint("Подходящего комплекта нет:", "1;31"))
        print("  " + resp.get("message", ""))
        history_text = resp.get("message", "Подходящего комплекта нет.")
    else:
        print(paint(f"Неожиданный статус: {status}", "1;31"))
        history_text = "Не удалось обработать запрос."
    if show_json:
        print(paint("\nJSON-ответ:", "2"))
        print(paint(json.dumps(resp, ensure_ascii=False, indent=2), "2"))
    return history_text or "Ответ получен."


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", default=os.path.join(HERE, "data", "catalog.json"))
    ap.add_argument("--json", action="store_true", help="показывать и сырой JSON-ответ")
    args = ap.parse_args()

    for stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass

    catalog_path = os.path.abspath(args.catalog)
    with open(catalog_path, encoding="utf-8-sig") as f:
        by_id = {x["id"]: x for x in json.load(f)}

    print(paint("=== ИИ-помощник покупателя ===", "1;36"))
    print("Опишите, что нужно: стол, кресло и/или лампа, город, общий бюджет.")
    print("Быстрые фразы (введите цифру):")
    for k, v in PRESETS.items():
        print(f"  {k} — {v}")
    print("Команды: /new — начать заново, /q — выход.\n")

    messages = []
    while True:
        try:
            raw = input(paint("Вы: ", "1;34")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not raw:
            continue
        if raw in ("/q", "/quit", "/exit"):
            break
        if raw == "/new":
            messages = []
            print(paint("Диалог сброшен.\n", "2"))
            continue
        text = PRESETS.get(raw, raw)
        if raw in PRESETS:
            print(paint(f"   → {text}", "2"))
        if len(messages) >= 19:
            print(paint("Диалог слишком длинный, начинаем заново.\n", "2"))
            messages = []

        messages.append({"role": "user", "text": text})
        print(paint("   думаю…", "2"), flush=True)
        t0 = time.time()
        try:
            proc = call_main(messages, catalog_path)
        except subprocess.TimeoutExpired:
            messages.pop()
            print(paint("Время ожидания вышло. Повторите запрос.\n", "1;31"))
            continue
        dt = time.time() - t0
        stderr_text = proc.stderr.decode("utf-8", "replace")
        if proc.returncode != 0:
            messages.pop()
            print(paint("Ошибка при обработке запроса:", "1;31"))
            print("  " + (stderr_text.strip().splitlines() or ["неизвестная ошибка"])[-1])
            print()
            continue
        try:
            resp = json.loads(proc.stdout.decode("utf-8"))
        except Exception as e:
            messages.pop()
            print(paint(f"Ответ не является JSON: {e}\n", "1;31"))
            continue

        reqs = extract_requirements_from_log(stderr_text)
        if reqs:
            print(paint("Модель поняла: " + understood(reqs), "2"))
        history_text = render(resp, by_id, args.json)
        print(paint(f"(ответ за {dt:.1f} с)\n", "2"))
        messages.append({"role": "assistant", "text": history_text})


if __name__ == "__main__":
    main()
