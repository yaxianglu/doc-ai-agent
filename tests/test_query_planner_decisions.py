import unittest

from doc_ai_agent.query_planner_decisions import (
    playbook_context_trace,
    query_type_for_window_follow_up,
    resolve_follow_up_question,
    should_use_playbook_route,
)


class QueryPlannerDecisionsTests(unittest.TestCase):
    def test_query_type_for_window_follow_up_keeps_joint_risk(self):
        self.assertEqual(query_type_for_window_follow_up("joint_risk", "pest"), "joint_risk")

    def test_should_use_playbook_route_rejects_advice_wording(self):
        self.assertFalse(
            should_use_playbook_route(
                question="为什么最近虫情高，还要给建议",
                heuristic_query_type="top",
                playbook_route={"query_type": "pest_top", "matched_terms": ["虫情"]},
                deterministic_query_types={"latest_device"},
                playbook_upgradeable_query_types={"top"},
                context={"domain": "pest"},
            )
        )

    def test_playbook_context_trace_includes_reason_and_engine(self):
        trace = playbook_context_trace(
            {
                "reason": "semantic pest trend",
                "retrieval_engine": "llamaindex",
                "matched_terms": ["虫情", "走势"],
            }
        )

        self.assertIn("semantic pest trend", trace)
        self.assertIn("playbook_router=llamaindex", trace)

    def test_resolve_follow_up_question_reuses_pending_domain_clarification(self):
        resolved = resolve_follow_up_question(
            "虫情",
            history=[],
            context={
                "pending_user_question": "近3个星期受灾最严重的地方是哪里",
                "pending_clarification": "agri_domain",
            },
        )

        self.assertEqual(resolved, "近3个星期受灾最严重的地方是哪里 虫情")


if __name__ == "__main__":
    unittest.main()
