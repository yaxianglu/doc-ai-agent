import json
import os
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from doc_ai_agent.config import AppConfig
from doc_ai_agent.server import build_http_server


def http_json(url: str, method: str = "GET", payload: dict | None = None, token: str | None = None):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, data=data, headers=headers, method=method)
    with urlopen(request) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


class HttpAuthTests(unittest.TestCase):
    def test_protected_routes_require_auth_and_login_flow_works(self):
        with tempfile.TemporaryDirectory() as td:
            repo_root = os.path.dirname(os.path.dirname(__file__))
            credentials_path = os.path.join(td, "auth-initial-credentials.txt")
            with open(credentials_path, "w", encoding="utf-8") as handle:
                handle.write("gago-1:StrongPass!123\n")
            cfg = AppConfig(
                data_dir=repo_root,
                db_path=os.path.join(td, "alerts.db"),
                refresh_interval_minutes=5,
                port=0,
                auth_db_path=os.path.join(td, "auth.db"),
                auth_bootstrap_path=credentials_path,
                openai_api_key="",
                openai_base_url="https://api.openai.com/v1",
                openai_router_model="gpt-4.1-mini",
                openai_advice_model="gpt-4.1",
                openai_timeout_seconds=30,
            )

            server = build_http_server(cfg)
            host, port = server.server_address
            base_url = f"http://{host}:{port}"
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                with self.assertRaises(HTTPError) as chat_error:
                    http_json(
                        f"{base_url}/chat",
                        method="POST",
                        payload={"question": "近3个月虫情最严重的县有哪些"},
                    )
                self.assertEqual(chat_error.exception.code, 401)

                _, login_payload = http_json(
                    f"{base_url}/auth/login",
                    method="POST",
                    payload={"username": "gago-1", "password": "StrongPass!123"},
                )
                token = login_payload["token"]
                self.assertEqual(login_payload["user"]["username"], "gago-1")

                _, me_payload = http_json(f"{base_url}/auth/me", token=token)
                self.assertEqual(me_payload["user"]["username"], "gago-1")

                _, chat_payload = http_json(
                    f"{base_url}/chat",
                    method="POST",
                    payload={"question": "2026年以来发生了多少预警信息？"},
                    token=token,
                )
                self.assertIn("answer", chat_payload)

                _, _ = http_json(f"{base_url}/auth/logout", method="POST", token=token)

                with self.assertRaises(HTTPError) as me_error:
                    http_json(f"{base_url}/auth/me", token=token)
                self.assertEqual(me_error.exception.code, 401)
            finally:
                server.shutdown()
                server.server_close()
                worker.join(timeout=1)


if __name__ == "__main__":
    unittest.main()
