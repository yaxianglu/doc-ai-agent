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

    def answer(self, question: str) -> AdviceResult:
        sources = []
        if self.source_provider is not None:
            sources = self.source_provider.search(question, limit=3)

        if self.llm_client and self.model:
            source_text = ""
            if sources:
                source_text = "\n".join(
                    [
                        f"- 标题:{s.get('title','')} 日期:{s.get('published_at','')} 摘要:{s.get('snippet','')}"
                        for s in sources
                    ]
                )
            system_prompt = (
                "你是农业灾害处置助手。请给出可执行的分步骤建议，"
                "包括先做什么、再做什么、风险点与复查项，控制在180字内。"
            )
            user_prompt = question
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
        return AdviceResult(
            answer="建议结合当前告警类型、作物和天气过程做分区处置，并由农技人员复核后执行。",
            sources=sources or ["通用处置规则（MVP占位）"],
            generation_mode="rule",
            model="",
        )
