import unittest

from doc_ai_agent.agent_orchestration import PlanNodeOutcome, resolve_planning_question, route_target, update_plan_outcome


class AgentOrchestrationTests(unittest.TestCase):
    def test_resolve_planning_question_prefers_original_follow_up_for_context_explanation(self):
        question = resolve_planning_question(
            "为什么",
            {
                "used_context": True,
                "needs_explanation": True,
                "needs_historical": False,
                "needs_forecast": False,
                "needs_advice": False,
                "normalized_question": "徐州市 虫情 为什么",
            },
        )

        self.assertEqual(question, "为什么")

    def test_update_plan_outcome_adds_forecast_execution_when_route_is_forecast(self):
        plan = {
            "route": {"query_type": "pest_forecast"},
            "task_graph": {"execution_plan": ["understand_request", "answer_synthesis"]},
        }
        understanding = {
            "needs_forecast": False,
            "needs_historical": True,
        }

        outcome = update_plan_outcome(plan=plan, understanding=understanding)

        self.assertIsInstance(outcome, PlanNodeOutcome)
        self.assertTrue(outcome.understanding["needs_forecast"])
        self.assertFalse(outcome.understanding["needs_historical"])
        self.assertEqual(outcome.understanding["execution_plan"], ["understand_request", "forecast", "answer_synthesis"])

    def test_route_target_prefers_advice_when_no_analysis_needed(self):
        target = route_target(
            {"intent": "advice", "needs_clarification": False},
            {"needs_historical": False, "needs_forecast": False, "needs_explanation": False, "needs_advice": False},
        )

        self.assertEqual(target, "advice")


if __name__ == "__main__":
    unittest.main()
