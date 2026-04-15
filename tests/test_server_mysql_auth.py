import unittest
from unittest.mock import MagicMock, patch

from doc_ai_agent.auth import fixed_bootstrap_credentials
from doc_ai_agent.config import AppConfig
from doc_ai_agent.server import AgentApp


class ServerMySQLAuthTests(unittest.TestCase):
    @patch("doc_ai_agent.server.DocAIAgent")
    @patch("doc_ai_agent.server.create_query_playbook_router", return_value=None)
    @patch("doc_ai_agent.server.load_source_provider", return_value=None)
    @patch("doc_ai_agent.server.AuthService")
    @patch("doc_ai_agent.server.MySQLRepository")
    def test_mysql_runtime_uses_mysql_repo_for_auth_and_fixed_seed(
        self,
        mysql_repo_cls,
        auth_service_cls,
        _source_provider,
        _playbook_router,
        _agent_cls,
    ):
        mysql_repo = MagicMock()
        mysql_repo_cls.return_value = mysql_repo

        cfg = AppConfig(
            data_dir=".",
            db_path="./data/alerts.db",
            refresh_interval_minutes=5,
            port=8000,
            db_url="mysql://tester:secret@127.0.0.1:3306/doc-cloud",
            openai_api_key="",
            openai_base_url="https://api.openai.com/v1",
            openai_router_model="gpt-4.1-mini",
            openai_advice_model="gpt-4.1",
            openai_timeout_seconds=30,
        )

        app = AgentApp(cfg)

        auth_service_cls.assert_called_once_with(mysql_repo, session_ttl_days=cfg.auth_session_ttl_days)
        auth_service_cls.return_value.ensure_users.assert_called_once_with(fixed_bootstrap_credentials())
        mysql_repo.create_tables.assert_called_once()
        self.assertIs(app.repo, mysql_repo)


if __name__ == "__main__":
    unittest.main()
