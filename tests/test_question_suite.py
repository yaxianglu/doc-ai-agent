import os
import tempfile
import unittest

from doc_ai_agent.config import AppConfig
from doc_ai_agent.server import build_app


class QuestionSuiteTests(unittest.TestCase):
    def test_recommended_questions(self):
        repo_root = os.path.dirname(os.path.dirname(__file__))
        with tempfile.TemporaryDirectory() as td:
            cfg = AppConfig(
                data_dir=repo_root,
                db_path=os.path.join(td, "alerts.db"),
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

            data_questions = [
                "2025年12月24日全省一共发生了多少条预警？",
                "2025年12月24日涝渍等级预警有多少条？",
                "2025年12月24日重旱等级预警有多少条？",
                "徐州市在2025年12月24日发生了多少条预警？",
                "2025年12月24日各城市预警数量 Top5 是哪些？",
                "2025年12月24日哪个区县预警最多？",
                "告警值最高的10条记录分别是什么（时间、设备、地区、告警值）？",
                "告警值超过150的预警有多少条？主要集中在哪些城市？",
                "设备SNS00204659最近一次预警时间、等级、处置建议是什么？",
                "昆山市花桥镇这条预警的处置建议是什么？",
                "沛县相关预警里，哪些记录sms_content为空？",
                "相同设备在连续两天都触发预警的有哪些？",
                "按告警等级分组，平均告警值分别是多少？",
                "土壤墒情仪类型预警中，墒情预警子类型占比多少？",
                "2025年12月23日到12月24日，徐州市预警数量变化了多少？",
            ]

            for question in data_questions:
                result = app.chat(question)
                self.assertEqual(result["mode"], "data_query", msg=question)
                self.assertTrue(bool(result["answer"]), msg=question)
                self.assertNotEqual(result["answer"], "自1970-01-01以来，预警信息共 1288 条。", msg=question)

            advice_questions = [
                "针对涝渍预警，给出一份可执行的24小时处置清单。",
                "对重旱地块，按大田/设施大棚/林果分别给建议。",
                "如果同一设备连续两天涝渍，优先排查哪些问题？",
                "对告警值异常高（如>160）的地块，先排水还是先停灌？给出判断依据。",
                "请把处置建议改写成面向农户的短信版本（80字内）。",
            ]

            for question in advice_questions:
                result = app.chat(question)
                self.assertIn(result["mode"], {"advice", "data_query"}, msg=question)
                self.assertTrue(bool(result["answer"]), msg=question)


if __name__ == "__main__":
    unittest.main()
