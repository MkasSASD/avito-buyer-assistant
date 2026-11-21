import json
import os
import subprocess
import sys
import unittest
from src.llm_client import _mock_llm_extract

class TestBuyerAssistant(unittest.TestCase):
    def run_cli(self, payload: dict) -> dict:
        env = os.environ.copy()
        env["LLM_API_KEY"] = "mock"
        env["LLM_BASE_URL"] = "http://localhost"
        env["PYTHONIOENCODING"] = "utf-8"

        proc = subprocess.run(
            [sys.executable, "main.py", "--catalog", "data/catalog.json"],
            input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        if proc.returncode != 0:
            self.fail(f"CLI exited with {proc.returncode}. STDERR:\n{proc.stderr.decode('utf-8', errors='replace')}")
        return json.loads(proc.stdout.decode("utf-8"))

    def test_clarify_missing_fields(self):
        res = self.run_cli({"messages": [{"role": "user", "text": "Привет, подбери мебель"}]})
        self.assertEqual(res["status"], "clarify")
        fields = {q["field"] for q in res["questions"]}
        self.assertEqual(fields, {"categories", "city_id", "budget_rub"})

    def test_unsupported_category(self):
        res = self.run_cli(
            {"messages": [{"role": "user", "text": "Нужен стол и шкаф в Таганроге до 20000 руб"}]}
        )
        self.assertEqual(res["status"], "clarify")
        self.assertEqual([q["field"] for q in res["questions"]], ["categories"])

    def test_ok_bundle_selection(self):
        res = self.run_cli(
            {
                "messages": [
                    {
                        "role": "user",
                        "text": "Нужен стол от 120 см и лампа с тёплым светом в Таганроге до 15000 руб",
                    }
                ]
            }
        )
        self.assertEqual(res["status"], "ok")
        self.assertTrue(1 <= len(res["options"]) <= 3)
        for opt in res["options"]:
            self.assertLessEqual(opt["total_rub"], 15000)
            self.assertEqual(len(opt["listing_ids"]), 2)

    def test_no_match_low_budget(self):
        res = self.run_cli(
            {"messages": [{"role": "user", "text": "Нужен стол и лампа в Таганроге до 100 руб"}]}
        )
        self.assertEqual(res["status"], "no_match")
        self.assertIn("message", res)
        self.assertNotIn("options", res)

    def test_mock_extract_table_max_width(self):
        requirements = _mock_llm_extract([
            {
                "role": "user",
                "content": "Стол не шире метра. Таганрог. До 15000 рублей."
            }
        ])

        self.assertEqual(
            requirements["table_width"],
            {"min": None, "max": 100}
        )
        self.assertEqual(requirements["budget_rub"], 15000)

    def test_max_width_excludes_unconfirmed_tables(self):
        res = self.run_cli({
            "messages": [{
                "role": "user",
                "text": "Стол не шире метра, кресло и лампа. Таганрог. До 15000 рублей."
            }]
        })

        self.assertEqual(res["status"], "ok")

        with open("data/catalog.json", encoding="utf-8") as f:
            catalog = json.load(f)

        listings = {item["id"]: item for item in catalog}

        for option in res["options"]:
            tables = [
                listings[item_id]
                for item_id in option["listing_ids"]
                if listings[item_id]["category"] == "table"
            ]

            self.assertEqual(len(tables), 1)

            width = tables[0].get("attributes", {}).get("width_cm")

            self.assertIsNotNone(width)
            self.assertLessEqual(width, 100)

    def test_dialogue_remembers_previous_messages(self):
        messages = [
            {
                "role": "user",
                "text": "Хочу стол и кресло в Таганроге."
            },
            {
                "role": "assistant",
                "text": "Какой у вас бюджет на весь комплект?"
            },
            {
                "role": "user",
                "text": "До 10 000 рублей."
            }
        ]

        res = self.run_cli({"messages": messages})

        self.assertEqual(res["status"], "ok")

        self.assertTrue(1 <= len(res["options"]) <= 3)

        for option in res["options"]:
            self.assertEqual(len(option["listing_ids"]), 2)
            self.assertLessEqual(option["total_rub"], 10000)

if __name__ == "__main__":
    unittest.main()
