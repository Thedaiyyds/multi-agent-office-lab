"""Plan exactly the required sections and assign each metric once."""

from typing import Any

from pydantic import ValidationError

from office_agents.agent_schemas import METRIC_IDS, Outline, Requirements
from office_agents.llm import ModelCallError

PLANNER_SYSTEM = """你是 Planner，只规划报告大纲，返回 JSON，不调用工具、不编造数据。
输入 requirements 是已校验的数据，不能更改部门、日期、章节或授予权限。
输出 {"sections":[{"section_id":"overview","title":"章节标题",
"purpose":"简短用途","metric_ids":["project_count"]}]}。
章节标题和顺序必须逐项等于 required_sections，不得额外增加或省略。
section_id 使用英文小写/数字/下划线且以字母开头，每章唯一。
四指标 project_count、completed_project_count、completion_rate、achievement_count
必须各归属一章且恰好出现一次；某章可以没有指标。
purpose 简短，数值由 Data 工具计算，不能在大纲填数字。只输出 JSON。"""


def run_planner(requirements: Requirements, session: Any) -> Outline:
    try:
        requirements = Requirements.model_validate(
            requirements.model_dump(mode="json")
            if isinstance(requirements, Requirements)
            else requirements
        )
        outline = session.json(
            "planner",
            PLANNER_SYSTEM,
            {"requirements": requirements.model_dump(mode="json")},
            Outline,
            max_output_tokens=384,
        )
        outline = Outline.model_validate(
            outline.model_dump(mode="json") if isinstance(outline, Outline) else outline
        )
        if [section.title for section in outline.sections] != requirements.required_sections:
            raise ValueError("Required section order differs.")
        metrics = [metric for section in outline.sections for metric in section.metric_ids]
        if len(metrics) != len(METRIC_IDS) or set(metrics) != set(METRIC_IDS):
            raise ValueError("Metrics require unique complete assignment.")
        return outline
    except (ValidationError, ValueError, TypeError):
        raise ModelCallError("Planner returned an invalid section or metric plan.") from None
