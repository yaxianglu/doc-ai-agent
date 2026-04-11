import os
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from doc_ai_agent.config import AppConfig
from doc_ai_agent.server import AgentApp, build_app


class ServerTests(unittest.TestCase):
    def test_refresh_and_chat(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "alerts.db")
            repo_root = os.path.dirname(os.path.dirname(__file__))
            cfg = AppConfig(
                data_dir=repo_root,
                db_path=db_path,
                refresh_interval_minutes=5,
                port=0,
                openai_api_key="",
                openai_base_url="https://api.openai.com/v1",
                openai_router_model="gpt-4.1-mini",
                openai_advice_model="gpt-4.1",
                openai_timeout_seconds=30,
            )
            app = build_app(cfg)

            inserted = app.refresh()
            self.assertGreater(inserted, 0)

            payload = {"question": "2026年以来发生了多少预警信息？"}
            chat_data = app.chat(payload["question"])
            self.assertEqual(chat_data["mode"], "data_query")
            self.assertTrue(bool(chat_data["answer"]))

    def test_chat_returns_clarification_for_ambiguous_severity_question(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "alerts.db")
            repo_root = os.path.dirname(os.path.dirname(__file__))
            cfg = AppConfig(
                data_dir=repo_root,
                db_path=db_path,
                refresh_interval_minutes=5,
                port=0,
                openai_api_key="",
                openai_base_url="https://api.openai.com/v1",
                openai_router_model="gpt-4.1-mini",
                openai_advice_model="gpt-4.1",
                openai_timeout_seconds=30,
            )
            app = build_app(cfg)
            app.refresh()

            chat_data = app.chat("近3个星期，受灾最严重的地方是哪里")

            self.assertEqual(chat_data["mode"], "advice")
            self.assertIn("虫情", chat_data["answer"])
            self.assertIn("墒情", chat_data["answer"])
            self.assertEqual(chat_data["evidence"]["generation_mode"], "clarification")

    def test_chat_returns_data_query_for_explicit_weekly_pest_question(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "alerts.db")
            repo_root = os.path.dirname(os.path.dirname(__file__))
            cfg = AppConfig(
                data_dir=repo_root,
                db_path=db_path,
                refresh_interval_minutes=5,
                port=0,
                openai_api_key="",
                openai_base_url="https://api.openai.com/v1",
                openai_router_model="gpt-4.1-mini",
                openai_advice_model="gpt-4.1",
                openai_timeout_seconds=30,
            )
            app = build_app(cfg)
            app.refresh()

            chat_data = app.chat("近3个星期虫情最严重的地方是哪里？")

            self.assertEqual(chat_data["mode"], "data_query")
            self.assertTrue(bool(chat_data["answer"]))
            expected_since = (datetime.now() - timedelta(days=21)).strftime("%Y-%m-%d 00:00:00")
            self.assertEqual(chat_data["evidence"].get("since"), expected_since)

    def test_chat_uses_history_for_short_follow_up(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "alerts.db")
            repo_root = os.path.dirname(os.path.dirname(__file__))
            cfg = AppConfig(
                data_dir=repo_root,
                db_path=db_path,
                refresh_interval_minutes=5,
                port=0,
                openai_api_key="",
                openai_base_url="https://api.openai.com/v1",
                openai_router_model="gpt-4.1-mini",
                openai_advice_model="gpt-4.1",
                openai_timeout_seconds=30,
            )
            app = build_app(cfg)
            app.refresh()

            chat_data = app.chat(
                "虫情",
                history=[
                    {"role": "user", "content": "过去5个月灾害最严重的地方是哪里"},
                    {"role": "assistant", "content": "你想看虫情还是墒情？"},
                ],
            )

            self.assertEqual(chat_data["mode"], "data_query")
            self.assertEqual(chat_data["processing"]["data_query"], "SQLite / SQL")

    def test_chat_uses_thread_id_for_follow_up_without_explicit_history(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "alerts.db")
            repo_root = os.path.dirname(os.path.dirname(__file__))
            cfg = AppConfig(
                data_dir=repo_root,
                db_path=db_path,
                refresh_interval_minutes=5,
                port=0,
                openai_api_key="",
                openai_base_url="https://api.openai.com/v1",
                openai_router_model="gpt-4.1-mini",
                openai_advice_model="gpt-4.1",
                openai_timeout_seconds=30,
                memory_store_path=os.path.join(td, "agent-memory.json"),
            )
            app = build_app(cfg)
            app.refresh()

            clarification = app.chat("近3个星期，受灾最严重的地方是哪里", thread_id="thread-1")
            follow_up = app.chat("虫情", thread_id="thread-1")

            self.assertEqual(clarification["mode"], "advice")
            self.assertEqual(follow_up["mode"], "data_query")
            self.assertEqual(follow_up["processing"]["orchestration"], "LangGraph")
            self.assertEqual(follow_up["processing"]["memory"], "LocalMemory")
            self.assertTrue(follow_up["evidence"]["request_understanding"]["used_context"])
            self.assertEqual(follow_up["evidence"]["memory_state"]["memory_version"], 2)
            self.assertEqual(follow_up["evidence"]["memory_state"]["domain"], "pest")
            self.assertEqual(
                follow_up["evidence"]["request_understanding"]["resolved_question"],
                "近3个星期虫情最严重的地方是哪里",
            )

    def test_chat_greeting_ignores_thread_context_and_returns_intro(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "alerts.db")
            repo_root = os.path.dirname(os.path.dirname(__file__))
            cfg = AppConfig(
                data_dir=repo_root,
                db_path=db_path,
                refresh_interval_minutes=5,
                port=0,
                openai_api_key="",
                openai_base_url="https://api.openai.com/v1",
                openai_router_model="gpt-4.1-mini",
                openai_advice_model="gpt-4.1",
                openai_timeout_seconds=30,
                memory_store_path=os.path.join(td, "agent-memory.json"),
            )
            app = build_app(cfg)
            app.refresh()

            first_turn = app.chat("过去5个月常州虫情最严重的地方是哪里", thread_id="thread-greeting")
            chat_data = app.chat("你好", thread_id="thread-greeting")

            self.assertEqual(chat_data["mode"], "advice")
            self.assertIn("AI农情工作台", chat_data["answer"])
            self.assertNotIn("常州市", chat_data["answer"])
            self.assertFalse(chat_data["evidence"]["request_understanding"]["used_context"])
            self.assertEqual(chat_data["evidence"]["generation_mode"], "rule")
            self.assertEqual(chat_data["processing"]["retrieval"], "未使用")
            self.assertEqual(
                chat_data["evidence"]["memory_state"]["query_type"],
                first_turn["evidence"]["memory_state"]["query_type"],
            )
            self.assertEqual(
                chat_data["evidence"]["memory_state"]["region_name"],
                first_turn["evidence"]["memory_state"]["region_name"],
            )

    def test_chat_returns_execution_plan_for_mixed_analysis_request(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "alerts.db")
            repo_root = os.path.dirname(os.path.dirname(__file__))
            cfg = AppConfig(
                data_dir=repo_root,
                db_path=db_path,
                refresh_interval_minutes=5,
                port=0,
                openai_api_key="",
                openai_base_url="https://api.openai.com/v1",
                openai_router_model="gpt-4.1-mini",
                openai_advice_model="gpt-4.1",
                openai_timeout_seconds=30,
                memory_store_path=os.path.join(td, "agent-memory.json"),
            )
            app = build_app(cfg)
            app.refresh()

            chat_data = app.chat("过去5个月墒情最严重的地方是哪里，未来两周会怎样，为什么，给建议", thread_id="thread-mixed")

            self.assertIn("execution_plan", chat_data["evidence"])
            self.assertIn("task_graph", chat_data["evidence"])
            self.assertIn("analysis_context", chat_data["evidence"])
            self.assertIn("request_understanding", chat_data["evidence"])
            self.assertEqual(chat_data["evidence"]["forecast"]["forecast_backend"], "statsforecast")
            self.assertEqual(chat_data["evidence"]["forecast"]["model_name"], "AutoETS")
            self.assertEqual(
                [task["type"] for task in chat_data["evidence"]["task_graph"]["tasks"]],
                ["historical_rank", "cause_retrieval", "forecast", "advice_retrieval", "merge_answer"],
            )

    def test_latest_device_query_returns_disposal_suggestion_when_requested(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "alerts.db")
            repo_root = os.path.dirname(os.path.dirname(__file__))
            cfg = AppConfig(
                data_dir=repo_root,
                db_path=db_path,
                refresh_interval_minutes=5,
                port=0,
                openai_api_key="",
                openai_base_url="https://api.openai.com/v1",
                openai_router_model="gpt-4.1-mini",
                openai_advice_model="gpt-4.1",
                openai_timeout_seconds=30,
            )
            app = build_app(cfg)
            app.refresh()

            chat_data = app.chat("设备SNS00204659最近一次预警时间、等级、处置建议是什么？")

            self.assertEqual(chat_data["mode"], "data_query")
            self.assertIn("处置建议", chat_data["answer"])
            self.assertIn("尽快排水散墒", chat_data["answer"])

    def test_highest_value_query_lists_key_record_fields_in_answer(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "alerts.db")
            repo_root = os.path.dirname(os.path.dirname(__file__))
            cfg = AppConfig(
                data_dir=repo_root,
                db_path=db_path,
                refresh_interval_minutes=5,
                port=0,
                openai_api_key="",
                openai_base_url="https://api.openai.com/v1",
                openai_router_model="gpt-4.1-mini",
                openai_advice_model="gpt-4.1",
                openai_timeout_seconds=30,
            )
            app = build_app(cfg)
            app.refresh()

            chat_data = app.chat("告警值最高的5条记录有哪些？")

            self.assertEqual(chat_data["mode"], "data_query")
            self.assertIn("1.", chat_data["answer"])
            self.assertIn("SNS", chat_data["answer"])
            self.assertIn("告警值", chat_data["answer"])

    def test_new_full_question_does_not_leak_previous_thread_context(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "alerts.db")
            repo_root = os.path.dirname(os.path.dirname(__file__))
            cfg = AppConfig(
                data_dir=repo_root,
                db_path=db_path,
                refresh_interval_minutes=5,
                port=0,
                openai_api_key="",
                openai_base_url="https://api.openai.com/v1",
                openai_router_model="gpt-4.1-mini",
                openai_advice_model="gpt-4.1",
                openai_timeout_seconds=30,
                memory_store_path=os.path.join(td, "agent-memory.json"),
            )
            app = build_app(cfg)
            app.refresh()

            app.chat("过去5个月墒情最严重的地方是哪里，未来两周会怎样，为什么，给建议", thread_id="thread-isolation")
            follow_up = app.chat("设备SNS00204659最近一次预警时间、等级、处置建议是什么？", thread_id="thread-isolation")

            self.assertEqual(follow_up["mode"], "data_query")
            self.assertIn("处置建议", follow_up["answer"])

    def test_refresh_mysql_imports_enrichment_alert_rows(self):
        class FakeRepo:
            def __init__(self):
                self.inserted_alert_rows = []

            def begin_batch(self, *args, **kwargs):
                return "batch-1"

            def finish_batch(self, *args, **kwargs):
                return None

            def upsert_regions(self, rows):
                list(rows)
                return 0

            def upsert_devices(self, rows):
                list(rows)
                return 0

            def bulk_upsert_pest(self, rows):
                list(rows)
                return 0

            def bulk_upsert_soil(self, rows):
                list(rows)
                return 0

            def enrich_soil_dimensions(self):
                return None

            def insert_alerts(self, rows):
                payload = list(rows)
                self.inserted_alert_rows.extend(payload)
                return len(payload)

        app = object.__new__(AgentApp)
        app.repo = FakeRepo()
        app.config = AppConfig(
            data_dir="/tmp/data",
            db_path="/tmp/alerts.db",
            refresh_interval_minutes=5,
            port=0,
            db_url="mysql://dev:password@127.0.0.1:3306/doc-cloud",
            enrichment_xlsx_path="/tmp/enrichment.xlsx",
        )

        def fake_exists(path):
            return path == "/tmp/enrichment.xlsx"

        with patch("doc_ai_agent.server.glob.glob", return_value=["/tmp/data/虫情.xlsx", "/tmp/data/墒情.xlsx"]), patch(
            "doc_ai_agent.server.iter_pest_rows",
            return_value=iter(
                [
                    {
                        "device_sn": "P1",
                        "device_name": "虫情设备",
                        "device_type": "虫情仪",
                        "city_name": "徐州市",
                        "county_name": "睢宁县",
                        "monitor_time": "2026-04-10 00:00:00",
                    }
                ]
            ),
        ), patch(
            "doc_ai_agent.server.iter_soil_rows",
            return_value=iter([{"device_sn": "S1"}]),
        ), patch(
            "doc_ai_agent.server.iter_device_mappings_from_alert_xlsx",
            return_value=iter([{"device_sn": "S1", "city_name": "徐州市", "county_name": "睢宁县", "town_name": "姚集镇"}]),
        ), patch(
            "doc_ai_agent.server.load_alerts_from_xlsx",
            return_value=[
                {
                    "device_code": "SNS00204659",
                    "city": "徐州市",
                    "county": "睢宁县",
                    "region_name": "姚集镇",
                    "alert_time": "2025-12-24 00:00:00",
                    "alert_level": "涝渍",
                    "alert_type": "土壤墒情仪",
                    "alert_subtype": "墒情预警",
                    "alert_value": "168.36",
                    "sms_content": "建议尽快排水散墒",
                    "disposal_suggestion": "建议尽快排水散墒",
                    "source_file": "处置建议发布任务.xlsx",
                    "source_sheet": "sheet1",
                    "source_row": 8,
                }
            ],
        ), patch("doc_ai_agent.server.os.path.exists", side_effect=fake_exists):
            inserted = AgentApp._refresh_mysql(app)

        self.assertEqual(inserted["alerts"], 1)
        self.assertEqual(len(app.repo.inserted_alert_rows), 1)
        self.assertEqual(app.repo.inserted_alert_rows[0]["device_code"], "SNS00204659")

    def test_refresh_mysql_skips_heavy_import_when_structured_tables_already_loaded(self):
        class FakeRepo:
            def create_tables(self):
                return None

            def structured_data_ready(self):
                return True

        app = object.__new__(AgentApp)
        app.repo = FakeRepo()
        app.config = AppConfig(
            data_dir="/tmp/data",
            db_path="/tmp/alerts.db",
            refresh_interval_minutes=5,
            port=0,
            db_url="mysql://dev:password@127.0.0.1:3306/doc-cloud",
            enrichment_xlsx_path="/tmp/enrichment.xlsx",
        )

        with patch("doc_ai_agent.server.glob.glob") as glob_mock, patch(
            "doc_ai_agent.server.load_alerts_from_xlsx"
        ) as alerts_mock:
            inserted = AgentApp._refresh_mysql(app)

        self.assertEqual(inserted, {"pest": 0, "soil": 0, "device_mapping": 0, "alerts": 0, "skipped": True})
        glob_mock.assert_not_called()
        alerts_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
