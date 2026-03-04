from __future__ import annotations

import glob
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

from .agent import DocAIAgent
from .config import AppConfig
from .openai_client import OpenAIClient
from .repository import AlertRepository
from .source_provider import load_static_sources
from .xlsx_loader import load_alerts_from_xlsx


class AgentApp:
    def __init__(self, config: AppConfig):
        self.config = config
        self.repo = AlertRepository(config.db_path)
        self.repo.init_schema()
        llm_client = None
        if config.openai_api_key:
            llm_client = OpenAIClient(
                api_key=config.openai_api_key,
                base_url=config.openai_base_url,
                timeout_seconds=config.openai_timeout_seconds,
            )
        source_provider = load_static_sources(config.source_catalog_path)
        self.agent = DocAIAgent(
            self.repo,
            llm_client=llm_client,
            router_model=config.openai_router_model,
            advice_model=config.openai_advice_model,
            source_provider=source_provider,
        )

    def refresh(self) -> int:
        inserted = 0
        for path in sorted(glob.glob(os.path.join(self.config.data_dir, "*.xlsx"))):
            rows = load_alerts_from_xlsx(path)
            inserted += self.repo.insert_alerts(rows)
        return inserted

    def chat(self, question: str) -> dict:
        if not question:
            raise ValueError("question is required")
        return self.agent.answer(question)


def build_http_server(config: AppConfig) -> HTTPServer:
    app = AgentApp(config)

    class Handler(BaseHTTPRequestHandler):
        def _json(self, status: int, payload: dict) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/health":
                self._json(200, {"status": "ok"})
                return
            self._json(404, {"error": "not found"})

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length) if length else b"{}"
            payload = json.loads(body.decode("utf-8") or "{}")

            if self.path == "/refresh":
                inserted = app.refresh()
                self._json(200, {"inserted": inserted})
                return

            if self.path == "/chat":
                question = payload.get("question", "")
                if not question:
                    self._json(400, {"error": "question is required"})
                    return
                self._json(200, app.chat(question))
                return

            self._json(404, {"error": "not found"})

        def log_message(self, format: str, *args):
            return

    server = HTTPServer(("127.0.0.1", config.port), Handler)
    server.app = app
    return server


def build_app(config: AppConfig) -> AgentApp:
    return AgentApp(config)
