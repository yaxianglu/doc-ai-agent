"""应用配置模块。

该模块负责把环境变量解析成 `AppConfig`，并统一处理路径类配置：
- 支持相对路径（相对于项目根目录）
- 支持 `~` 用户目录展开
- 支持部分字段允许空字符串（表示“未启用”）
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _parse_env_file(path: Path) -> dict[str, str]:
    """读取简单的 `.env` 文件格式。"""
    if not path.exists() or not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def _resolve_env_file(raw_value: str | None) -> Path | None:
    """把 env 文件路径解析成绝对路径。"""
    if raw_value in {None, ""}:
        return None
    path = Path(raw_value).expanduser()
    if not path.is_absolute():
        path = (PROJECT_ROOT / path).resolve()
    return path


def _merge_env_with_files(env: Mapping[str, str]) -> dict[str, str]:
    """合并默认 env 文件与显式环境变量，显式值优先。"""
    merged: dict[str, str] = {}
    default_candidates = [PROJECT_ROOT / ".env.local", PROJECT_ROOT / ".env"]
    explicit_candidate = _resolve_env_file(env.get("DOC_AGENT_ENV_FILE"))
    for candidate in default_candidates + ([explicit_candidate] if explicit_candidate else []):
        if candidate is None:
            continue
        merged.update(_parse_env_file(candidate))
    merged.update(dict(env))
    return merged


def _resolve_path(raw_value: str | None, default: str, *, allow_empty: bool = False) -> str:
    """把环境变量中的路径值规范化为可直接使用的绝对路径字符串。"""
    candidate = raw_value if raw_value not in (None, "") else default
    if allow_empty and candidate == "":
        # 某些配置允许显式空值，例如可选的 Excel 增强文件路径。
        return ""
    path = Path(candidate).expanduser()
    if not path.is_absolute():
        # 相对路径统一挂到项目根目录，避免运行目录变化带来的路径歧义。
        path = (PROJECT_ROOT / path).resolve()
    return str(path)


@dataclass(frozen=True)
class AppConfig:
    """应用运行时配置对象。"""
    data_dir: str
    db_path: str
    refresh_interval_minutes: int
    port: int
    auth_session_ttl_days: int = 7
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
        """从环境变量映射中创建配置实例。"""
        merged_env = _merge_env_with_files(env)
        return cls(
            data_dir=_resolve_path(merged_env.get("DOC_AGENT_DATA_DIR"), "."),
            db_path=_resolve_path(merged_env.get("DOC_AGENT_DB_PATH"), "./data/alerts.db"),
            refresh_interval_minutes=int(merged_env.get("DOC_AGENT_REFRESH_MINUTES", "5")),
            port=int(merged_env.get("DOC_AGENT_PORT", "8000")),
            auth_session_ttl_days=int(merged_env.get("DOC_AGENT_AUTH_SESSION_TTL_DAYS", "7")),
            db_url=merged_env.get("DOC_AGENT_DB_URL", ""),
            openai_api_key=merged_env.get("OPENAI_API_KEY", ""),
            openai_base_url=merged_env.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            openai_router_model=merged_env.get("OPENAI_ROUTER_MODEL", "gpt-4.1-mini"),
            openai_advice_model=merged_env.get("OPENAI_ADVICE_MODEL", "gpt-4.1"),
            openai_timeout_seconds=int(merged_env.get("OPENAI_TIMEOUT_SECONDS", "30")),
            source_catalog_path=_resolve_path(merged_env.get("DOC_AGENT_SOURCE_CATALOG"), "./data/knowledge_sources.json"),
            source_provider_backend=merged_env.get("DOC_AGENT_SOURCE_PROVIDER", "static"),
            source_provider_embedding_model=merged_env.get("DOC_AGENT_SOURCE_EMBEDDING_MODEL", "text-embedding-3-small"),
            source_provider_qdrant_path=_resolve_path(merged_env.get("DOC_AGENT_SOURCE_QDRANT_PATH"), "./data/qdrant"),
            source_provider_qdrant_collection=merged_env.get("DOC_AGENT_SOURCE_QDRANT_COLLECTION", "knowledge_sources"),
            query_playbook_backend=merged_env.get("DOC_AGENT_QUERY_PLAYBOOK_BACKEND", "llamaindex"),
            query_playbook_embedding_model=merged_env.get("DOC_AGENT_QUERY_PLAYBOOK_EMBEDDING_MODEL", "text-embedding-3-small"),
            enrichment_xlsx_path=_resolve_path(merged_env.get("DOC_AGENT_ENRICHMENT_XLSX"), "", allow_empty=True),
            memory_store_path=_resolve_path(merged_env.get("DOC_AGENT_MEMORY_STORE_PATH"), "./data/agent-memory.json"),
            letta_base_url=merged_env.get("LETTA_BASE_URL", ""),
            letta_api_key=merged_env.get("LETTA_API_KEY", ""),
            letta_block_prefix=merged_env.get("LETTA_BLOCK_PREFIX", "doc-cloud-thread"),
        )
