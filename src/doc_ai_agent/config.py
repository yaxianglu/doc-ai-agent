from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class AppConfig:
    data_dir: str
    db_path: str
    refresh_interval_minutes: int
    port: int
    db_url: str = ""
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_router_model: str = "gpt-4.1-mini"
    openai_advice_model: str = "gpt-4.1"
    openai_timeout_seconds: int = 30
    source_catalog_path: str = "./data/knowledge_sources.json"
    source_provider_backend: str = "static"
    source_provider_embedding_model: str = "text-embedding-3-small"
    source_provider_qdrant_path: str = "./data/qdrant"
    source_provider_qdrant_collection: str = "knowledge_sources"
    query_playbook_backend: str = "llamaindex"
    query_playbook_embedding_model: str = "text-embedding-3-small"
    enrichment_xlsx_path: str = ""
    memory_store_path: str = "./data/agent-memory.json"
    letta_base_url: str = ""
    letta_api_key: str = ""
    letta_block_prefix: str = "doc-cloud-thread"

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "AppConfig":
        return cls(
            data_dir=env.get("DOC_AGENT_DATA_DIR", "."),
            db_path=env.get("DOC_AGENT_DB_PATH", "./data/alerts.db"),
            refresh_interval_minutes=int(env.get("DOC_AGENT_REFRESH_MINUTES", "5")),
            port=int(env.get("DOC_AGENT_PORT", "8000")),
            db_url=env.get("DOC_AGENT_DB_URL", ""),
            openai_api_key=env.get("OPENAI_API_KEY", ""),
            openai_base_url=env.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            openai_router_model=env.get("OPENAI_ROUTER_MODEL", "gpt-4.1-mini"),
            openai_advice_model=env.get("OPENAI_ADVICE_MODEL", "gpt-4.1"),
            openai_timeout_seconds=int(env.get("OPENAI_TIMEOUT_SECONDS", "30")),
            source_catalog_path=env.get("DOC_AGENT_SOURCE_CATALOG", "./data/knowledge_sources.json"),
            source_provider_backend=env.get("DOC_AGENT_SOURCE_PROVIDER", "static"),
            source_provider_embedding_model=env.get("DOC_AGENT_SOURCE_EMBEDDING_MODEL", "text-embedding-3-small"),
            source_provider_qdrant_path=env.get("DOC_AGENT_SOURCE_QDRANT_PATH", "./data/qdrant"),
            source_provider_qdrant_collection=env.get("DOC_AGENT_SOURCE_QDRANT_COLLECTION", "knowledge_sources"),
            query_playbook_backend=env.get("DOC_AGENT_QUERY_PLAYBOOK_BACKEND", "llamaindex"),
            query_playbook_embedding_model=env.get("DOC_AGENT_QUERY_PLAYBOOK_EMBEDDING_MODEL", "text-embedding-3-small"),
            enrichment_xlsx_path=env.get("DOC_AGENT_ENRICHMENT_XLSX", ""),
            memory_store_path=env.get("DOC_AGENT_MEMORY_STORE_PATH", "./data/agent-memory.json"),
            letta_base_url=env.get("LETTA_BASE_URL", ""),
            letta_api_key=env.get("LETTA_API_KEY", ""),
            letta_block_prefix=env.get("LETTA_BLOCK_PREFIX", "doc-cloud-thread"),
        )
