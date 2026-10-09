"""Dynamic local HTTP fixtures: consume actual contexts, never read a dataset.

This limited parser is an offline demonstration, not general language understanding.
Only Data's actual registered tool reads files and computes authoritative metrics.
"""

import json
import re
from datetime import date

import httpx

from office_agents.agent_schemas import DEFAULT_SECTIONS, METRIC_IDS


def _manager_fixture(context):
    text = context["user_text"]
    department_match = re.search(r"部门[：:]\s*([^\s，,；;。]+)", text)
    department = (
        department_match.group(1)
        if department_match
        else next((name for name in ("研发部", "市场部", "财务部") if name in text), None)
    )
    dates = re.findall(r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)", text)
    if len(dates) < 2:
        quarter_match = re.search(
            r"(?<!\d)(\d{4})\s*年?\s*(?:第\s*([一二三四1234])\s*季度|[Qq]([1-4]))", text
        )
        if quarter_match:
            year = int(quarter_match.group(1))
            quarter_text = quarter_match.group(2) or quarter_match.group(3)
            quarter = {"一": 1, "二": 2, "三": 3, "四": 4}.get(quarter_text)
            quarter = quarter if quarter is not None else int(quarter_text)
            dates = [
                date(year, (quarter - 1) * 3 + 1, 1).isoformat(),
                (
                    date(year + 1, 1, 1) if quarter == 4 else date(year, quarter * 3 + 1, 1)
                ).isoformat(),
            ]
    missing = ([] if department else ["department"]) + ([] if len(dates) >= 2 else ["date_range"])
    if missing:
        return {
            "status": "needs_input",
            "requirements": None,
            "missing_fields": missing,
            "questions": ["请提供部门和明确年份季度或起止 ISO 日期。"],
        }
    sections_match = re.search(r"章节[：:]\s*(.+)", text)
    sections = (
        [part.strip() for part in re.split(r"[，,、；;]", sections_match.group(1)) if part.strip()]
        if sections_match
        else context.get("default_sections", DEFAULT_SECTIONS)
    )
    return {
        "status": "ready",
        "requirements": {
            "department": department,
            "start_date": dates[0],
            "end_date": dates[1],
            "required_sections": sections,
            "output_format": "markdown",
        },
        "missing_fields": [],
        "questions": [],
    }


def workflow_mock_response(request: httpx.Request) -> httpx.Response:
    """Public handler for deterministic tests to wrap and inject failures."""
    try:
        payload = json.loads(request.content)
        messages = payload["messages"]
        role = messages[0]["content"].splitlines()[0].removeprefix("ROLE=")
        user = next(message for message in messages if message["role"] == "user")
        context = json.loads(user["content"])
        if role == "manager":
            output = _manager_fixture(context)
        elif role == "planner":
            titles = context["requirements"]["required_sections"]
            output = {
                "sections": [
                    {
                        "section_id": f"part_{index + 1}",
                        "title": title,
                        "purpose": "离线脚本按实际需求规划章节，指标由工具提供。",
                        "metric_ids": list(METRIC_IDS[:3])
                        + ([METRIC_IDS[3]] if len(titles) == 1 else [])
                        if index == 0
                        else ([METRIC_IDS[3]] if index == 1 else []),
                    }
                    for index, title in enumerate(titles)
                ]
            }
        elif role == "data":
            tool_messages = [message for message in messages if message["role"] == "tool"]
            if not tool_messages:
                return httpx.Response(
                    200,
                    json={
                        "choices": [
                            {
                                "finish_reason": "tool_calls",
                                "message": {
                                    "content": None,
                                    "tool_calls": [
                                        {
                                            "id": "workflow-tool-call",
                                            "type": "function",
                                            "function": {
                                                "name": "run_data_tools",
                                                "arguments": json.dumps(
                                                    context, ensure_ascii=False
                                                ),
                                            },
                                        }
                                    ],
                                },
                            }
                        ]
                    },
                )
            tool_result = json.loads(tool_messages[-1]["content"])
            output = {
                "summary": "离线 HTTP 脚本已收到实际工具结果。"
                + ("无匹配数据。" if tool_result["status"] == "no_data" else "统计已完成。"),
                "limitations": ["问题材料未筛选；脚本响应不是模型生成。"],
            }
        elif role == "writer":
            outline = context["outline"]["sections"]
            assignment = {
                metric: section["section_id"]
                for section in outline
                for metric in section["metric_ids"]
            }
            output = {
                "sections": [
                    {
                        "section_id": section["section_id"],
                        "title": section["title"],
                        "text": "根据本次实际工具提供的指标汇报工作；此正文为离线脚本响应。",
                    }
                    for section in outline
                ],
                "fact_claims": [
                    {"section_id": assignment[metric["metric_id"]], **metric}
                    for metric in context["metrics"]
                ],
                "suggestions": [
                    {"section_id": outline[-1]["section_id"], "text": "建议持续更新项目快照。"}
                ],
                "issue_scope": "unfiltered",
            }
        elif role == "checker":
            # Deliberately permissive: the real program checks must still reject bad facts.
            output = {
                "passed": True,
                "issues": [],
                "revision_instructions": [],
                "needs_input": False,
            }
        else:
            return httpx.Response(400)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps(output, ensure_ascii=False)},
                    }
                ]
            },
        )
    except (KeyError, TypeError, ValueError, StopIteration, OverflowError):
        return httpx.Response(400)


def make_workflow_mock_transport() -> httpx.MockTransport:
    return httpx.MockTransport(workflow_mock_response)
