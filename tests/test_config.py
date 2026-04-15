import os
import tempfile
import unittest
from pathlib import Path

from doc_ai_agent.config import AppConfig


class ConfigTests(unittest.TestCase):
    def test_defaults(self):
        cfg = AppConfig.from_env({})
        repo_root = Path(__file__).resolve().parents[1]
        self.assertEqual(cfg.data_dir, str(repo_root))
        self.assertEqual(cfg.refresh_interval_minutes, 5)
        self.assertEqual(cfg.db_path, str(repo_root / "data" / "alerts.db"))
        self.assertEqual(cfg.openai_base_url, "https://api.openai.com/v1")
        self.assertEqual(cfg.openai_router_model, "gpt-4.1-mini")
        self.assertEqual(cfg.openai_advice_model, "gpt-4.1")
        self.assertEqual(cfg.openai_timeout_seconds, 30)
        self.assertEqual(cfg.openai_api_key, "")
        self.assertEqual(cfg.source_catalog_path, str(repo_root / "data" / "knowledge_sources.json"))
        self.assertEqual(cfg.source_provider_backend, "static")
        self.assertEqual(cfg.source_provider_embedding_model, "text-embedding-3-small")
        self.assertEqual(cfg.source_provider_qdrant_path, str(repo_root / "data" / "qdrant"))
        self.assertEqual(cfg.source_provider_qdrant_collection, "knowledge_sources")
        self.assertEqual(cfg.query_playbook_backend, "llamaindex")
        self.assertEqual(cfg.query_playbook_embedding_model, "text-embedding-3-small")

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
            "DOC_AGENT_SOURCE_PROVIDER": "qdrant",
            "DOC_AGENT_SOURCE_EMBEDDING_MODEL": "text-embedding-3-large",
            "DOC_AGENT_SOURCE_QDRANT_PATH": "/tmp/qdrant",
            "DOC_AGENT_SOURCE_QDRANT_COLLECTION": "agri_sources",
            "DOC_AGENT_QUERY_PLAYBOOK_BACKEND": "static",
            "DOC_AGENT_QUERY_PLAYBOOK_EMBEDDING_MODEL": "text-embedding-3-large",
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
        self.assertEqual(cfg.source_provider_backend, "qdrant")
        self.assertEqual(cfg.source_provider_embedding_model, "text-embedding-3-large")
        self.assertEqual(cfg.source_provider_qdrant_path, "/tmp/qdrant")
        self.assertEqual(cfg.source_provider_qdrant_collection, "agri_sources")
        self.assertEqual(cfg.query_playbook_backend, "static")
        self.assertEqual(cfg.query_playbook_embedding_model, "text-embedding-3-large")

    def test_relative_overrides_resolve_from_repo_root(self):
        repo_root = Path(__file__).resolve().parents[1]
        cfg = AppConfig.from_env(
            {
                "DOC_AGENT_DATA_DIR": "fixtures/data",
                "DOC_AGENT_DB_PATH": "runtime/alerts.db",
                "DOC_AGENT_SOURCE_CATALOG": "runtime/sources.json",
                "DOC_AGENT_SOURCE_QDRANT_PATH": "runtime/qdrant",
                "DOC_AGENT_MEMORY_STORE_PATH": "runtime/memory.json",
            }
        )
        self.assertEqual(cfg.data_dir, str(repo_root / "fixtures" / "data"))
        self.assertEqual(cfg.db_path, str(repo_root / "runtime" / "alerts.db"))
        self.assertEqual(cfg.source_catalog_path, str(repo_root / "runtime" / "sources.json"))
        self.assertEqual(cfg.source_provider_qdrant_path, str(repo_root / "runtime" / "qdrant"))
        self.assertEqual(cfg.memory_store_path, str(repo_root / "runtime" / "memory.json"))

    def test_explicit_env_file_is_loaded(self):
        with tempfile.TemporaryDirectory() as td:
            env_file = Path(td) / "agent.env"
            env_file.write_text(
                "\n".join(
                    [
                        "DOC_AGENT_DB_URL=mysql://dev:password@127.0.0.1:3306/doc-cloud",
                        "OPENAI_API_KEY=sk-from-file",
                        "DOC_AGENT_PORT=8123",
                    ]
                ),
                encoding="utf-8",
            )

            cfg = AppConfig.from_env({"DOC_AGENT_ENV_FILE": str(env_file)})

            self.assertEqual(cfg.db_url, "mysql://dev:password@127.0.0.1:3306/doc-cloud")
            self.assertEqual(cfg.openai_api_key, "sk-from-file")
            self.assertEqual(cfg.port, 8123)

    def test_explicit_env_values_override_env_file(self):
        with tempfile.TemporaryDirectory() as td:
            env_file = Path(td) / "agent.env"
            env_file.write_text(
                "\n".join(
                    [
                        "DOC_AGENT_DB_URL=mysql://dev:password@127.0.0.1:3306/doc-cloud",
                        "OPENAI_API_KEY=sk-from-file",
                    ]
                ),
                encoding="utf-8",
            )

            cfg = AppConfig.from_env(
                {
                    "DOC_AGENT_ENV_FILE": str(env_file),
                    "DOC_AGENT_DB_URL": "mysql://prod:secret@127.0.0.1:3306/doc-cloud-prod",
                    "OPENAI_API_KEY": "sk-from-env",
                }
            )

            self.assertEqual(cfg.db_url, "mysql://prod:secret@127.0.0.1:3306/doc-cloud-prod")
            self.assertEqual(cfg.openai_api_key, "sk-from-env")


if __name__ == "__main__":
    unittest.main()
