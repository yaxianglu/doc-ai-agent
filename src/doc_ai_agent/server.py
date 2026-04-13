from __future__ import annotations

import glob
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Dict, Iterable, Optional

from .agent import DocAIAgent
from .auth import AuthRepository, AuthService, load_or_create_credentials
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
    def __init__(self, config: AppConfig):
        self.config = config
        self.auth_repo = AuthRepository(config.auth_db_path)
        self.auth_repo.init_schema()
        self.auth = AuthService(self.auth_repo, session_ttl_days=config.auth_session_ttl_days)
        auth_usernames = [item.strip() for item in config.auth_usernames.split(",") if item.strip()]
        self.bootstrap_credentials = load_or_create_credentials(config.auth_bootstrap_path, auth_usernames)
        self.auth.ensure_users(self.bootstrap_credentials)
        if config.db_url:
            self.repo = MySQLRepository(config.db_url)
            self.repo.create_tables()
        else:
            self.repo = AlertRepository(config.db_path)
            self.repo.init_schema()
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
        inserted = {"pest": 0, "soil": 0, "device_mapping": 0, "alerts": 0}
        if hasattr(self.repo, "structured_data_ready") and self.repo.structured_data_ready():
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
        if isinstance(self.repo, MySQLRepository):
            return self._refresh_mysql()

        inserted = 0
        for path in sorted(glob.glob(os.path.join(self.config.data_dir, "*.xlsx"))):
            rows = load_alerts_from_xlsx(path)
            inserted += self.repo.insert_alerts(rows)
        return inserted

    def chat(self, question: str, history: object = None, thread_id: str | None = None) -> dict:
        if not question:
            raise ValueError("question is required")
        return self.agent.answer(question, history=history, thread_id=thread_id)

    def login(self, username: str, password: str) -> dict | None:
        return self.auth.login(username, password)

    def current_user(self, token: str) -> dict | None:
        return self.auth.authenticate(token)

    def logout(self, token: str) -> None:
        self.auth.logout(token)


def build_http_server(config: AppConfig) -> HTTPServer:
    app = AgentApp(config)

    class Handler(BaseHTTPRequestHandler):
        def _read_json(self) -> dict:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length) if length else b"{}"
            return json.loads(body.decode("utf-8") or "{}")

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

        def do_GET(self):
            if self.path == "/health":
                self._json(200, {"status": "ok"})
                return
            if self.path == "/auth/me":
                user = self._require_user()
                if user is None:
                    return
                self._json(200, {"user": user})
                return
            self._json(404, {"error": "not found"})

        def do_POST(self):
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

            self._json(404, {"error": "not found"})

        def log_message(self, format: str, *args):
            return

    server = HTTPServer(("127.0.0.1", config.port), Handler)
    server.app = app
    return server


def build_app(config: AppConfig) -> AgentApp:
    return AgentApp(config)
