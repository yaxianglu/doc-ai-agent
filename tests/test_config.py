import os
import unittest

from doc_ai_agent.config import AppConfig


class ConfigTests(unittest.TestCase):
    def test_defaults(self):
        cfg = AppConfig.from_env({})
        self.assertEqual(cfg.data_dir, ".")
        self.assertEqual(cfg.refresh_interval_minutes, 5)
        self.assertEqual(cfg.db_path, "./data/alerts.db")
        self.assertEqual(cfg.openai_base_url, "https://api.openai.com/v1")
        self.assertEqual(cfg.openai_router_model, "gpt-4.1-mini")
        self.assertEqual(cfg.openai_advice_model, "gpt-4.1")
        self.assertEqual(cfg.openai_timeout_seconds, 30)
        self.assertEqual(cfg.openai_api_key, "")
        self.assertEqual(cfg.source_catalog_path, "./data/knowledge_sources.json")

    def test_overrides(self):
        env = {
            "DOC_AGENT_DATA_DIR": "/tmp/data",
            "DOC_AGENT_DB_PATH": "/tmp/alerts.db",
            "DOC_AGENT_REFRESH_MINUTES": "15",
            "DOC_AGENT_PORT": "9000",
            "OPENAI_API_KEY": "sk-test",
            "OPENAI_BASE_URL": "https://example.com/v1",
            "OPENAI_ROUTER_MODEL": "gpt-4o-mini",
            "OPENAI_ADVICE_MODEL": "gpt-4o",
            "OPENAI_TIMEOUT_SECONDS": "60",
            "DOC_AGENT_SOURCE_CATALOG": "/tmp/sources.json",
        }
        cfg = AppConfig.from_env(env)
        self.assertEqual(cfg.data_dir, "/tmp/data")
        self.assertEqual(cfg.db_path, "/tmp/alerts.db")
        self.assertEqual(cfg.refresh_interval_minutes, 15)
        self.assertEqual(cfg.port, 9000)
        self.assertEqual(cfg.openai_api_key, "sk-test")
        self.assertEqual(cfg.openai_base_url, "https://example.com/v1")
        self.assertEqual(cfg.openai_router_model, "gpt-4o-mini")
        self.assertEqual(cfg.openai_advice_model, "gpt-4o")
        self.assertEqual(cfg.openai_timeout_seconds, 60)
        self.assertEqual(cfg.source_catalog_path, "/tmp/sources.json")


if __name__ == "__main__":
    unittest.main()
