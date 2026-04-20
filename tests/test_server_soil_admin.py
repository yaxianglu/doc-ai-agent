import json
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from urllib import request, error
from urllib.parse import quote

from doc_ai_agent.config import AppConfig
from doc_ai_agent.server import build_http_server


class FakeAdminApp:
    def __init__(self):
        self.calls = []

    def current_user(self, token):
        if token == "valid-token":
            return {"id": 1, "username": "gago-1"}
        return None

    def list_soil_records(self, filters, page, page_size):
        self.calls.append(("list", filters, page, page_size))
        return {"rows": [{"record_id": "r1"}], "total": 1, "page": page, "page_size": page_size, "total_pages": 1}

    def update_soil_record_field(self, record_id, field, value, user):
        self.calls.append(("update", record_id, field, value, user["username"]))
        return {"record_id": record_id, "field": field, "old_value": "徐州市", "new_value": value}

    def delete_soil_records(self, record_ids, user):
        self.calls.append(("delete", record_ids, user["username"]))
        return {"deleted_count": len(record_ids), "records": [{"record_id": record_ids[0]}] if record_ids else []}

    def upload_soil_excel(self, filename, content_base64, mode, confirm_full_replace, user):
        self.calls.append(("upload", filename, mode, confirm_full_replace, user["username"]))
        return {"mode": mode, "raw_rows": 2, "loaded_rows": 2}


def config():
    return AppConfig(
        data_dir=".",
        db_path=":memory:",
        refresh_interval_minutes=5,
        port=0,
        openai_api_key="",
        openai_base_url="https://api.openai.com/v1",
        openai_router_model="gpt-4.1-mini",
        openai_advice_model="gpt-4.1",
        openai_timeout_seconds=30,
    )


class ServerSoilAdminTests(unittest.TestCase):
    def _request(self, server, method, path, payload=None, token="valid-token"):
        body = json.dumps(payload or {}).encode("utf-8") if payload is not None else None
        headers = {"Authorization": f"Bearer {token}"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        encoded_path = quote(path, safe="/?=&")
        req = request.Request(f"http://127.0.0.1:{server.server_port}{encoded_path}", data=body, headers=headers, method=method)
        thread = threading.Thread(target=server.handle_request)
        thread.start()
        try:
            with request.urlopen(req, timeout=3) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))
        finally:
            thread.join(timeout=3)

    def test_admin_list_requires_auth(self):
        fake_app = FakeAdminApp()
        with patch("doc_ai_agent.server.AgentApp", return_value=fake_app):
            server = build_http_server(config())
        try:
            status, payload = self._request(server, "GET", "/admin/soil/records", token="bad-token")
        finally:
            server.server_close()

        self.assertEqual(status, 401)
        self.assertEqual(payload["error"], "authentication required")

    def test_admin_list_passes_filters_and_pagination(self):
        fake_app = FakeAdminApp()
        with patch("doc_ai_agent.server.AgentApp", return_value=fake_app):
            server = build_http_server(config())
        try:
            status, payload = self._request(server, "GET", "/admin/soil/records?page=2&page_size=25&city_name=徐州市&soil_anomaly_type=low")
        finally:
            server.server_close()

        self.assertEqual(status, 200)
        self.assertEqual(payload["page"], 2)
        self.assertEqual(fake_app.calls[0], ("list", {"city_name": "徐州市", "soil_anomaly_type": "low"}, 2, 25))

    def test_admin_patch_updates_one_field(self):
        fake_app = FakeAdminApp()
        with patch("doc_ai_agent.server.AgentApp", return_value=fake_app):
            server = build_http_server(config())
        try:
            status, payload = self._request(server, "PATCH", "/admin/soil/records/r1", {"field": "city_name", "value": "南京市"})
        finally:
            server.server_close()

        self.assertEqual(status, 200)
        self.assertEqual(payload["new_value"], "南京市")
        self.assertEqual(fake_app.calls[0][0], "update")

    def test_admin_bulk_delete_accepts_ids_only(self):
        fake_app = FakeAdminApp()
        with patch("doc_ai_agent.server.AgentApp", return_value=fake_app):
            server = build_http_server(config())
        try:
            status, payload = self._request(server, "POST", "/admin/soil/records/bulk-delete", {"record_ids": ["r1", "r2"]})
        finally:
            server.server_close()

        self.assertEqual(status, 200)
        self.assertEqual(payload["deleted_count"], 2)
        self.assertEqual(fake_app.calls[0], ("delete", ["r1", "r2"], "gago-1"))

    def test_admin_upload_requires_full_replace_confirmation(self):
        fake_app = FakeAdminApp()
        with patch("doc_ai_agent.server.AgentApp", return_value=fake_app):
            server = build_http_server(config())
        try:
            status, payload = self._request(server, "POST", "/admin/soil/upload", {"filename": "soil.xlsx", "content_base64": "eA==", "mode": "replace"})
        finally:
            server.server_close()

        self.assertEqual(status, 400)
        self.assertIn("confirm", payload["error"])
        self.assertEqual(fake_app.calls, [])


if __name__ == "__main__":
    unittest.main()
