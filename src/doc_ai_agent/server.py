"""服务接入层：初始化仓储与 Agent，并提供 HTTP 接口。"""

from __future__ import annotations

import glob
import json
import os
import base64
import tempfile
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Dict, Iterable, Optional
from urllib.parse import parse_qs, unquote, urlparse

from .agent import DocAIAgent
from .auth import AuthService, MemoryAuthRepository, fixed_bootstrap_credentials
from .config import AppConfig
from .mysql_repository import MySQLRepository
from .openai_client import OpenAIClient
from .pest_loader import iter_rows as iter_pest_rows
from .query_playbook_router import create_query_playbook_router
from .request_understanding_backend import InstructorUnderstandingBackend
from .repository import AlertRepository
from .soil_loader import iter_device_mappings_from_alert_xlsx, iter_rows as iter_soil_rows
from .source_provider import load_source_provider
from .xlsx_loader import load_alerts_from_xlsx


class AgentApp:
    """应用容器：负责资源初始化、数据刷新与聊天调用。"""
    def __init__(self, config: AppConfig):
        self.config = config
        self.bootstrap_credentials = fixed_bootstrap_credentials()
        if config.db_url:
            self.repo = MySQLRepository(config.db_url)
            self.repo.create_tables()
            self.auth_repo = self.repo
        else:
            self.auth_repo = MemoryAuthRepository()
            self.repo = AlertRepository(config.db_path)
            self.repo.init_schema()
        self.auth = AuthService(self.auth_repo, session_ttl_days=config.auth_session_ttl_days)
        if not config.db_url:
            # 内存模式仍保留固定账号，便于本地开发和单测；MySQL 运行态只读取既有用户表。
            self.auth.ensure_users(self.bootstrap_credentials)
        llm_client = None
        understanding_backend = None
        if config.openai_api_key:
            llm_client = OpenAIClient(
                api_key=config.openai_api_key,
                base_url=config.openai_base_url,
                timeout_seconds=config.openai_timeout_seconds,
            )
            try:
                understanding_backend = InstructorUnderstandingBackend(
                    api_key=config.openai_api_key,
                    base_url=config.openai_base_url,
                    model=config.openai_router_model,
                    timeout_seconds=config.openai_timeout_seconds,
                )
            except Exception:
                understanding_backend = None
        source_provider = load_source_provider(
            config.source_catalog_path,
            backend=config.source_provider_backend,
            openai_api_key=config.openai_api_key,
            embedding_model=config.source_provider_embedding_model,
            qdrant_path=config.source_provider_qdrant_path,
            qdrant_collection=config.source_provider_qdrant_collection,
        )
        query_playbook_router = create_query_playbook_router(
            backend=config.query_playbook_backend,
            openai_api_key=config.openai_api_key,
            embedding_model=config.query_playbook_embedding_model,
        )
        self.agent = DocAIAgent(
            self.repo,
            llm_client=llm_client,
            router_model=config.openai_router_model,
            advice_model=config.openai_advice_model,
            source_provider=source_provider,
            query_playbook_router=query_playbook_router,
            understanding_backend=understanding_backend,
            memory_store_path=config.memory_store_path,
            letta_base_url=config.letta_base_url,
            letta_api_key=config.letta_api_key,
            letta_block_prefix=config.letta_block_prefix,
        )

    def _refresh_mysql(self) -> dict:
        """将数据目录中的 Excel 批量导入 MySQL。"""
        inserted = {"pest": 0, "soil": 0, "device_mapping": 0, "alerts": 0}
        if hasattr(self.repo, "structured_data_ready") and self.repo.structured_data_ready():
            # 已完成结构化导入时直接跳过，避免重复写入。
            inserted["skipped"] = True
            return inserted
        data_files = sorted(glob.glob(os.path.join(self.config.data_dir, "*.xlsx")))

        for path in data_files:
            basename = os.path.basename(path)
            if basename == "虫情.xlsx":
                batch_id = self.repo.begin_batch("pest", basename, note="虫情 Excel 导入")
                rows = list(iter_pest_rows(path, batch_id))
                self.repo.upsert_regions(rows)
                self.repo.upsert_devices(
                    {
                        "device_sn": row.get("device_sn"),
                        "device_name": row.get("device_name"),
                        "device_type": row.get("device_type"),
                        "city_name": row.get("city_name"),
                        "county_name": row.get("county_name"),
                        "town_name": None,
                        "longitude": row.get("longitude"),
                        "latitude": row.get("latitude"),
                        "mapping_source": basename,
                        "mapping_confidence": "native_pest",
                        "first_seen_at": row.get("monitor_time"),
                        "last_seen_at": row.get("monitor_time"),
                    }
                    for row in rows
                )
                inserted["pest"] += self.repo.bulk_upsert_pest(rows)
                self.repo.finish_batch(batch_id, len(rows), len(rows), note="虫情导入完成")
            elif basename == "墒情.xlsx":
                batch_id = self.repo.begin_batch("soil", basename, note="墒情 Excel 导入")
                rows = list(iter_soil_rows(path, batch_id))
                inserted["soil"] += self.repo.bulk_upsert_soil(rows)
                self.repo.finish_batch(batch_id, len(rows), len(rows), note="墒情导入完成")
            else:
                continue

        enrichment_candidates = []
        if self.config.enrichment_xlsx_path and os.path.exists(self.config.enrichment_xlsx_path):
            enrichment_candidates.append(self.config.enrichment_xlsx_path)
        candidate = os.path.join(os.path.dirname(self.config.data_dir), "处置建议发布任务.xlsx")
        if os.path.exists(candidate) and candidate not in enrichment_candidates:
            enrichment_candidates.append(candidate)

        for path in enrichment_candidates:
            mappings = list(iter_device_mappings_from_alert_xlsx(path))
            inserted["device_mapping"] += self.repo.upsert_regions(mappings)
            inserted["device_mapping"] += self.repo.upsert_devices(
                {
                    **row,
                    "first_seen_at": None,
                    "last_seen_at": None,
                }
                for row in mappings
            )
            inserted["alerts"] += self.repo.insert_alerts(load_alerts_from_xlsx(path))

        if inserted["device_mapping"]:
            self.repo.enrich_soil_dimensions()
        return inserted

    def refresh(self):
        """按当前仓储类型刷新底层数据。"""
        if isinstance(self.repo, MySQLRepository):
            return self._refresh_mysql()

        inserted = 0
        for path in sorted(glob.glob(os.path.join(self.config.data_dir, "*.xlsx"))):
            rows = load_alerts_from_xlsx(path)
            inserted += self.repo.insert_alerts(rows)
        return inserted

    def chat(self, question: str, history: object = None, thread_id: str | None = None) -> dict:
        """调用 Agent 主入口处理一次对话请求。"""
        if not question:
            raise ValueError("question is required")
        return self.agent.answer(question, history=history, thread_id=thread_id)

    def login(self, username: str, password: str) -> dict | None:
        """执行用户名密码登录。"""
        return self.auth.login(username, password)

    def current_user(self, token: str) -> dict | None:
        """根据 token 获取当前登录用户。"""
        return self.auth.authenticate(token)

    def logout(self, token: str) -> None:
        """注销当前 token 对应的会话。"""
        self.auth.logout(token)

    def list_soil_records(self, filters: dict, page: int, page_size: int) -> dict:
        """分页查询墒情管理表。"""
        if not hasattr(self.repo, "admin_list_soil_records"):
            raise ValueError("soil admin requires mysql repository")
        return self.repo.admin_list_soil_records(filters=filters, page=page, page_size=page_size)

    def update_soil_record_field(self, record_id: str, field: str, value, user: dict) -> dict:
        """修改单条墒情记录的单个字段。"""
        if not hasattr(self.repo, "admin_update_soil_field"):
            raise ValueError("soil admin requires mysql repository")
        return self.repo.admin_update_soil_field(record_id, field, value, user)

    def delete_soil_records(self, record_ids: list[str], user: dict) -> dict:
        """按 ID 删除墒情记录。"""
        if not hasattr(self.repo, "admin_delete_soil_records"):
            raise ValueError("soil admin requires mysql repository")
        return self.repo.admin_delete_soil_records(record_ids, user)

    def upload_soil_excel(self, filename: str, content_base64: str, mode: str, confirm_full_replace: bool, user: dict) -> dict:
        """导入墒情 Excel，支持增量和全量覆盖。"""
        if not isinstance(self.repo, MySQLRepository):
            raise ValueError("soil upload requires mysql repository")
        normalized_mode = mode if mode in {"incremental", "replace"} else "incremental"
        if normalized_mode == "replace" and not confirm_full_replace:
            raise ValueError("confirm_full_replace is required for replace mode")
        if not filename.lower().endswith(".xlsx"):
            raise ValueError("only .xlsx files are supported")
        try:
            content = base64.b64decode(content_base64, validate=True)
        except Exception as exc:
            raise ValueError("invalid excel payload") from exc
        if not content:
            raise ValueError("excel file is empty")

        fd, path = tempfile.mkstemp(prefix="soil-admin-upload-", suffix=".xlsx")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
            batch_id = self.repo.begin_batch("soil_admin", filename, note=f"墒情后台{normalized_mode}导入")
            rows = list(iter_soil_rows(path, batch_id))
            if normalized_mode == "replace":
                loaded = self.repo.replace_soil_rows(rows)
            else:
                loaded = self.repo.bulk_insert_soil_incremental(rows)
            self.repo.finish_batch(batch_id, len(rows), loaded, note="墒情后台导入完成")
            if hasattr(self.repo, "_audit_admin_change"):
                self.repo._audit_admin_change(
                    "upload_replace" if normalized_mode == "replace" else "upload_incremental",
                    filename,
                    None,
                    {"filename": filename, "mode": normalized_mode, "raw_rows": len(rows), "loaded_rows": loaded},
                    user,
                )
            return {"filename": filename, "mode": normalized_mode, "raw_rows": len(rows), "loaded_rows": loaded}
        finally:
            try:
                os.remove(path)
            except OSError:
                pass


def build_http_server(config: AppConfig) -> HTTPServer:
    """构建 HTTPServer，并挂载健康检查/登录/聊天接口。"""
    app = AgentApp(config)

    class Handler(BaseHTTPRequestHandler):
        def _read_json(self) -> dict:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length) if length else b"{}"
            return json.loads(body.decode("utf-8") or "{}")

        def _parsed_url(self):
            return urlparse(self.path)

        @staticmethod
        def _first_query_value(query: dict, key: str, default: str = "") -> str:
            values = query.get(key)
            if not values:
                return default
            return values[0]

        def _json(self, status: int, payload: dict) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _bearer_token(self) -> str:
            auth_header = self.headers.get("Authorization", "")
            if not auth_header.startswith("Bearer "):
                return ""
            return auth_header[7:].strip()

        def _require_user(self) -> dict | None:
            user = app.current_user(self._bearer_token())
            if user is None:
                self._json(401, {"error": "authentication required"})
                return None
            return user

        def _require_admin_user(self) -> dict | None:
            user = self._require_user()
            if user is None:
                return None
            if user.get("role") != "admin":
                self._json(403, {"error": "admin role required"})
                return None
            return user

        def _handle_internal_error(self) -> None:
            """把未捕获异常统一收口为 JSON 500，避免客户端收到空响应。"""
            traceback.print_exc()
            try:
                self._json(500, {"error": "internal server error"})
            except BrokenPipeError:
                return

        def _handle_bad_request(self, error: Exception) -> None:
            self._json(400, {"error": str(error)})

        def do_GET(self):
            try:
                parsed_url = self._parsed_url()
                path = parsed_url.path
                if self.path == "/health":
                    self._json(200, {"status": "ok"})
                    return
                if path == "/auth/me":
                    user = self._require_user()
                    if user is None:
                        return
                    self._json(200, {"user": user})
                    return
                if path == "/admin/soil/records":
                    user = self._require_admin_user()
                    if user is None:
                        return
                    query = parse_qs(parsed_url.query)
                    filters = {}
                    for field in ["city_name", "county_name", "device_sn", "soil_anomaly_type", "sample_time_from", "sample_time_to"]:
                        value = self._first_query_value(query, field)
                        if value:
                            filters[field] = value
                    page = int(self._first_query_value(query, "page", "1") or "1")
                    page_size = int(self._first_query_value(query, "page_size", "50") or "50")
                    self._json(200, app.list_soil_records(filters, page, page_size))
                    return
                self._json(404, {"error": "not found"})
            except ValueError as error:
                self._handle_bad_request(error)
            except Exception:
                self._handle_internal_error()

        def do_POST(self):
            try:
                payload = self._read_json()

                if self.path == "/auth/login":
                    username = str(payload.get("username", "")).strip()
                    password = str(payload.get("password", ""))
                    result = app.login(username, password)
                    if result is None:
                        self._json(401, {"error": "用户名或密码错误"})
                        return
                    self._json(200, result)
                    return

                if self.path == "/auth/logout":
                    user = self._require_user()
                    if user is None:
                        return
                    app.logout(self._bearer_token())
                    self._json(200, {"ok": True, "user": user})
                    return

                if self.path == "/refresh":
                    if self._require_user() is None:
                        return
                    inserted = app.refresh()
                    self._json(200, {"inserted": inserted})
                    return

                if self.path == "/chat":
                    if self._require_user() is None:
                        return
                    question = payload.get("question", "")
                    if not question:
                        self._json(400, {"error": "question is required"})
                        return
                    self._json(200, app.chat(question, history=payload.get("history"), thread_id=payload.get("thread_id")))
                    return

                if self.path == "/admin/soil/records/bulk-delete":
                    user = self._require_admin_user()
                    if user is None:
                        return
                    record_ids = payload.get("record_ids")
                    if not isinstance(record_ids, list):
                        self._json(400, {"error": "record_ids is required"})
                        return
                    self._json(200, app.delete_soil_records([str(record_id) for record_id in record_ids], user))
                    return

                if self.path == "/admin/soil/upload":
                    user = self._require_admin_user()
                    if user is None:
                        return
                    mode = str(payload.get("mode") or "incremental")
                    confirm_full_replace = bool(payload.get("confirm_full_replace"))
                    if mode == "replace" and not confirm_full_replace:
                        self._json(400, {"error": "confirm_full_replace is required for replace mode"})
                        return
                    self._json(
                        200,
                        app.upload_soil_excel(
                            str(payload.get("filename") or ""),
                            str(payload.get("content_base64") or ""),
                            mode,
                            confirm_full_replace,
                            user,
                        ),
                    )
                    return

                self._json(404, {"error": "not found"})
            except ValueError as error:
                self._handle_bad_request(error)
            except Exception:
                self._handle_internal_error()

        def do_PATCH(self):
            try:
                parsed_url = self._parsed_url()
                path = parsed_url.path
                if path.startswith("/admin/soil/records/"):
                    user = self._require_admin_user()
                    if user is None:
                        return
                    record_id = unquote(path.rsplit("/", 1)[-1])
                    payload = self._read_json()
                    field = str(payload.get("field") or "")
                    if not field:
                        self._json(400, {"error": "field is required"})
                        return
                    self._json(200, app.update_soil_record_field(record_id, field, payload.get("value"), user))
                    return
                self._json(404, {"error": "not found"})
            except ValueError as error:
                self._handle_bad_request(error)
            except Exception:
                self._handle_internal_error()

        def do_DELETE(self):
            try:
                parsed_url = self._parsed_url()
                path = parsed_url.path
                if path.startswith("/admin/soil/records/"):
                    user = self._require_admin_user()
                    if user is None:
                        return
                    record_id = unquote(path.rsplit("/", 1)[-1])
                    self._json(200, app.delete_soil_records([record_id], user))
                    return
                self._json(404, {"error": "not found"})
            except ValueError as error:
                self._handle_bad_request(error)
            except Exception:
                self._handle_internal_error()

        def log_message(self, format: str, *args):
            return

    server = HTTPServer(("127.0.0.1", config.port), Handler)
    server.app = app
    return server


def build_app(config: AppConfig) -> AgentApp:
    """创建 AgentApp 实例，供脚本或测试复用。"""
    return AgentApp(config)
