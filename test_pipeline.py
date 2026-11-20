import json
import os
import subprocess
import sys
import unittest


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


if __name__ == "__main__":
    unittest.main()
