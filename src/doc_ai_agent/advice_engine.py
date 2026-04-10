from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AdviceResult:
    answer: str
    sources: list
    generation_mode: str
    model: str


class AdviceEngine:
    def __init__(self, llm_client=None, model: str = "", source_provider=None):
        self.llm_client = llm_client
        self.model = model
        self.source_provider = source_provider

    def answer(self, question: str, context: dict | None = None) -> AdviceResult:
        context = dict(context or {})
        normalized_question = str(question or "").strip()
        stripped_question = normalized_question.rstrip("？?")
        is_identity_question = stripped_question in {"你是谁", "你是干什么的", "你能做什么", "你可以做什么"}
        is_explanation_question = any(token in normalized_question for token in ["为什么", "原因", "依据"])
        sources = []
        if self.source_provider is not None:
            search_query = question
            if context.get("domain") == "pest" and context.get("region_name"):
                search_query = f"{context['region_name']} 虫情 防治建议"
            if context.get("domain") == "soil" and context.get("region_name"):
                search_query = f"{context['region_name']} 墒情 调度建议"
            try:
                sources = self.source_provider.search(search_query, limit=3, context=context)
            except TypeError:
                sources = self.source_provider.search(search_query, limit=3)

        if is_identity_question:
            return AdviceResult(
                answer="我是 AI农情工作台 助手，可以基于虫情、墒情历史数据做问答、趋势分析、预测判断，并给出处置建议。",
                sources=sources or [{"title": "内置身份说明", "url": "", "published_at": "", "snippet": ""}],
                generation_mode="rule",
                model="",
            )

        if self.llm_client and self.model:
            source_text = ""
            if sources:
                source_text = "\n".join(
                    [
                        f"- 标题:{s.get('title','')} 日期:{s.get('published_at','')} 摘要:{s.get('snippet','')}"
                        for s in sources
                    ]
                )
            if is_explanation_question:
                system_prompt = (
                    "你是农业风险解释助手。请基于上下文和资料，解释原因与判断依据。"
                    "优先回答为什么、哪些因素在起作用、接下来该重点复核什么，控制在180字内。"
                )
            else:
                system_prompt = (
                    "你是农业灾害处置助手。请给出可执行的分步骤建议，"
                    "包括先做什么、再做什么、风险点与复查项，控制在180字内。"
                )
            user_prompt = question
            if context:
                user_prompt = f"问题:{question}\n上下文:{context}"
            if source_text:
                user_prompt = f"{question}\n可参考资料:\n{source_text}"
            answer = self.llm_client.complete_text(self.model, system_prompt, user_prompt)
            if not sources:
                sources = [{"title": "OpenAI模型生成", "url": "", "published_at": "", "snippet": ""}]
            return AdviceResult(
                answer=answer,
                sources=sources,
                generation_mode="llm",
                model=self.model,
            )

        q = question
        domain = str(context.get("domain") or "")
        region_name = str(context.get("region_name") or "")
        forecast = context.get("forecast") or {}
        if is_explanation_question and domain == "pest":
            level = forecast.get("risk_level") or "中"
            return AdviceResult(
                answer=(
                    f"原因：{region_name or '当前地区'}虫情风险偏{level}，通常和近期监测值抬升、温湿条件适宜、局部田块防控不及时有关。"
                    "可以优先复核高值点位、诱捕器数据和阈值判断，再决定是否加密巡田或分区处置。"
                ),
                sources=sources or ["虫情解释规则库（Phase 2）"],
                generation_mode="rule",
                model="",
            )
        if is_explanation_question and domain == "soil":
            level = forecast.get("risk_level") or "中"
            return AdviceResult(
                answer=(
                    f"原因：{region_name or '当前地区'}墒情风险偏{level}，通常与近期降水偏离、灌排不均、土壤保水排水条件差有关。"
                    "可以先复核低墒/高墒分布，再结合未来天气判断是补灌还是排水。"
                ),
                sources=sources or ["墒情解释规则库（Phase 2）"],
                generation_mode="rule",
                model="",
            )
        if "台风" in q and "小麦" in q:
            return AdviceResult(
                answer=(
                    "台风后小麦建议：1) 先排水降渍，避免根系缺氧；2) 清沟理墒，减轻倒伏风险；"
                    "3) 叶面喷施磷酸二氢钾提升抗逆；4) 病害高发期加强赤霉病与纹枯病监测。"
                ),
                sources=sources or ["内置农业防灾规则库（MVP占位）"],
                generation_mode="rule",
                model="",
            )
        if domain == "pest":
            level = forecast.get("risk_level") or "中"
            return AdviceResult(
                answer=(
                    f"{region_name or '当前地区'}虫情风险{level}。建议：1) 先核查诱捕设备与田间样点；"
                    "2) 对高值地块优先做成虫/幼虫复核；3) 达到阈值后分区施策并复盘监测频次。"
                ),
                sources=sources or ["虫情处置规则库（Phase 2）"],
                generation_mode="rule",
                model="",
            )
        if domain == "soil":
            level = forecast.get("risk_level") or "中"
            return AdviceResult(
                answer=(
                    f"{region_name or '当前地区'}墒情风险{level}。建议：1) 先看低墒/高墒分布；"
                    "2) 低墒优先补灌，高墒优先排水；3) 结合未来天气滚动复测 3-5 天。"
                ),
                sources=sources or ["墒情调度规则库（Phase 2）"],
                generation_mode="rule",
                model="",
            )
        return AdviceResult(
            answer="建议结合当前告警类型、作物和天气过程做分区处置，并由农技人员复核后执行。",
            sources=sources or ["通用处置规则（MVP占位）"],
            generation_mode="rule",
            model="",
        )
