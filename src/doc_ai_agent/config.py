from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class AppConfig:
    data_dir: str
    db_path: str
    refresh_interval_minutes: int
    port: int
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_router_model: str = "gpt-4.1-mini"
    openai_advice_model: str = "gpt-4.1"
    openai_timeout_seconds: int = 30
    source_catalog_path: str = "./data/knowledge_sources.json"

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "AppConfig":
        return cls(
            data_dir=env.get("DOC_AGENT_DATA_DIR", "."),
            db_path=env.get("DOC_AGENT_DB_PATH", "./data/alerts.db"),
            refresh_interval_minutes=int(env.get("DOC_AGENT_REFRESH_MINUTES", "5")),
            port=int(env.get("DOC_AGENT_PORT", "8000")),
            openai_api_key=env.get("OPENAI_API_KEY", ""),
            openai_base_url=env.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            openai_router_model=env.get("OPENAI_ROUTER_MODEL", "gpt-4.1-mini"),
            openai_advice_model=env.get("OPENAI_ADVICE_MODEL", "gpt-4.1"),
            openai_timeout_seconds=int(env.get("OPENAI_TIMEOUT_SECONDS", "30")),
            source_catalog_path=env.get("DOC_AGENT_SOURCE_CATALOG", "./data/knowledge_sources.json"),
        )
