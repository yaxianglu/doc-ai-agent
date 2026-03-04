import os
import tempfile
import unittest

from doc_ai_agent.config import AppConfig
from doc_ai_agent.server import build_app


class ServerTests(unittest.TestCase):
    def test_refresh_and_chat(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "alerts.db")
            repo_root = os.path.dirname(os.path.dirname(__file__))
            cfg = AppConfig(
                data_dir=repo_root,
                db_path=db_path,
                refresh_interval_minutes=5,
                port=0,
                openai_api_key="",
                openai_base_url="https://api.openai.com/v1",
                openai_router_model="gpt-4.1-mini",
                openai_advice_model="gpt-4.1",
                openai_timeout_seconds=30,
            )
            app = build_app(cfg)

            inserted = app.refresh()
            self.assertGreater(inserted, 0)

            payload = {"question": "2026年以来发生了多少预警信息？"}
            chat_data = app.chat(payload["question"])
            self.assertEqual(chat_data["mode"], "data_query")
            self.assertTrue(bool(chat_data["answer"]))


if __name__ == "__main__":
    unittest.main()
