"""请求理解后端（LLM 结构化抽取）。

本模块定义了后端抽取输出的结构，并通过 Instructor + OpenAI 兼容接口，
把自然语言问题转换为稳定的结构化字段，供规则层融合使用。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field


class UnderstandingWindow(BaseModel):
    """时间窗结构。"""
    window_type: Literal["all", "months", "weeks", "days", "none"] = "none"
    window_value: int | None = None
    horizon_days: int | None = None


class UnderstandingExtraction(BaseModel):
    """语义抽取结果结构。"""
    domain: Literal["", "pest", "soil", "mixed"] = ""
    task_type: Literal["unknown", "ranking", "trend", "region_overview", "joint_risk", "data_detail"] = "unknown"
    region_name: str = ""
    region_level: Literal["", "city", "county"] = ""
    historical_window: UnderstandingWindow = Field(default_factory=UnderstandingWindow)
    future_window: UnderstandingWindow | None = None
    needs_explanation: bool = False
    needs_advice: bool = False


@dataclass
class InstructorUnderstandingBackend:
    """基于 Instructor 的语义抽取后端。"""
    api_key: str
    base_url: str
    model: str
    timeout_seconds: int = 20

    def __post_init__(self) -> None:
        """初始化 OpenAI 兼容客户端。"""
        import instructor
        from openai import OpenAI

        self._client = instructor.from_openai(
            OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.timeout_seconds,
            )
        )

    def extract(self, question: str, context: dict | None = None) -> dict | None:
        """调用后端模型抽取结构化语义。"""
        payload = {
            "question": question,
            "context": {
                "domain": str((context or {}).get("domain") or ""),
                "region_name": str((context or {}).get("region_name") or ""),
                "pending_clarification": str((context or {}).get("pending_clarification") or ""),
            },
        }
        try:
            result = self._client.chat.completions.create(
                model=self.model,
                temperature=0,
                response_model=UnderstandingExtraction,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是农业问题理解器。"
                            "请基于用户原问题抽取结构化语义，不要把地区概览问题改写成排行问题。"
                            "task_type 只能是：ranking、trend、region_overview、joint_risk、data_detail、unknown。"
                            "如果问题在问某个地区一段时间内的虫情/墒情情况、概况、整体表现、怎么样，"
                            "并且没有明显排行词，就用 region_overview。"
                            "如果问题在问某个地区一段时间内的虫情/墒情具体数据、明细、原始数据、具体数值，"
                            "就用 data_detail。"
                            "如果问题在问哪里最严重、最多、Top、排名，就用 ranking。"
                            "如果问题在问走势、趋势、变化，就用 trend。"
                            "如果问题同时问虫情和缺水/墒情叠加，就用 joint_risk。"
                            "尽量保留地区与时间窗。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(payload, ensure_ascii=False),
                    },
                ],
            )
        except Exception:
            return None
        if isinstance(result, BaseModel):
            return result.model_dump()
        return None
