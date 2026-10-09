"""Independent fixed role examples and explicit local HTTP fixtures."""

import json
from pathlib import Path

import httpx

from office_agents.agent_runtime import AgentRunReport, AgentSession
from office_agents.agent_schemas import (
    DEFAULT_SECTIONS,
    METRIC_IDS,
    DraftContent,
    DraftSection,
    FactClaim,
    Outline,
    OutlineSection,
    Requirements,
    RoleRun,
    Suggestion,
)
from office_agents.llm import ModelCallError
from office_agents.schemas import DataRequest
from office_agents.tools.metrics import run_data_tools

ROLES = ("manager", "planner", "data", "writer", "checker")


def sample_requirements(
    department="研发部", start_date="2026-04-01", end_date="2026-07-01", data_origin="simulated"
):
    return Requirements(
        department=department,
        start_date=start_date,
        end_date=end_date,
        data_origin=data_origin,
        required_sections=DEFAULT_SECTIONS,
    )


def sample_outline(requirements: Requirements) -> Outline:
    return Outline(
        sections=[
            OutlineSection(
                section_id=f"s{index + 1}",
                title=title,
                purpose="独立角色验收的固定输入大纲。",
                metric_ids=list(METRIC_IDS[:3])
                if index == 0
                else (["achievement_count"] if index == 1 else []),
            )
            for index, title in enumerate(requirements.required_sections)
        ]
    )


def _sample_data(data_root, requirements):
    return run_data_tools(
        data_root,
        DataRequest(
            department=requirements.department,
            start_date=requirements.start_date,
            end_date=requirements.end_date,
            data_origin=requirements.data_origin,
        ),
    )


def sample_content(outline: Outline, data) -> DraftContent:
    assignments = {
        metric: section.section_id for section in outline.sections for metric in section.metric_ids
    }
    return DraftContent(
        sections=[
            DraftSection(
                section_id=section.section_id,
                title=section.title,
                text=(
                    "按已校验的模拟统计说明本期工作。"
                    if data.request.data_origin == "simulated"
                    else "按已校验的提供数据说明本期工作。"
                )
                if data.status == "ok"
                else "本期缺少匹配数据。",
            )
            for section in outline.sections
        ],
        fact_claims=[
            FactClaim(
                section_id=assignments[metric.metric_id],
                metric_id=metric.metric_id,
                value=metric.value,
                unit=metric.unit,
                source_ids=metric.source_ids,
            )
            for metric in data.metrics
            if data.status == "ok"
        ],
        suggestions=[
            Suggestion(section_id=outline.sections[-1].section_id, text="建议持续更新项目快照。")
        ],
    )


def make_mock_transport(
    requirements: Requirements, data_root: str | Path, case="normal", role="all"
):
    """Scripted responses for exercising real modules; never represents a live model."""
    outline = sample_outline(requirements)
    content = (
        sample_content(outline, _sample_data(data_root, requirements))
        if role in {"all", "writer"}
        else None
    )
    calls = 0

    def handler(request: httpx.Request):
        nonlocal calls
        calls += 1
        payload = json.loads(request.content)
        role = payload["messages"][0]["content"].splitlines()[0].removeprefix("ROLE=")
        if role == "manager":
            output = (
                {
                    "status": "needs_input",
                    "missing_fields": ["department", "date_range"],
                    "questions": ["请提供部门和明确日期范围。"],
                }
                if case == "missing-requirements"
                else {"status": "ready", "requirements": requirements.model_dump(mode="json")}
            )
        elif role == "planner":
            output = outline.model_dump(mode="json")
        elif role == "data" and not any(
            message["role"] == "tool" for message in payload["messages"]
        ):
            arguments = {
                "department": requirements.department,
                "start_date": requirements.start_date.isoformat(),
                "end_date": requirements.end_date.isoformat(),
            }
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
                                        "id": f"mock-call-{calls}",
                                        "type": "function",
                                        "function": {
                                            "name": "run_data_tools",
                                            "arguments": json.dumps(arguments, ensure_ascii=False),
                                        },
                                    }
                                ],
                            },
                        }
                    ]
                },
            )
        elif role == "data":
            output = {
                "summary": "这是离线 HTTP 固定响应，不是模型生成。统计事实来自实际本地工具。",
                "limitations": ["问题材料未筛选。"],
            }
        elif role == "writer":
            if content is None:
                return httpx.Response(400, json={"error": "Writer fixture is not bound."})
            output = content.model_dump(mode="json")
        elif role == "checker":
            # Deliberately permissive: deterministic checks must catch injected errors.
            output = {
                "passed": True,
                "issues": [],
                "revision_instructions": [],
                "needs_input": False,
            }
        else:
            return httpx.Response(400, json={"error": "Unknown scripted role."})
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

    return httpx.MockTransport(handler)


def run_role_examples(
    session: AgentSession,
    *,
    role="all",
    data_root="data/samples",
    requirements: Requirements | None = None,
    case="normal",
    user_text: str | None = None,
) -> AgentRunReport:
    """Each role gets fixed independent inputs; outputs do not drive a workflow."""
    from office_agents.agent_schemas import Draft
    from office_agents.agents.checker import run_checker
    from office_agents.agents.data import run_data_agent
    from office_agents.agents.manager import run_manager
    from office_agents.agents.planner import run_planner
    from office_agents.agents.writer import render_draft, run_writer

    if role not in (*ROLES, "all") or case not in {"normal", "bad-draft", "missing-requirements"}:
        raise ModelCallError("Unsupported independent example.")
    if case == "missing-requirements" and role != "manager":
        raise ModelCallError("Missing-requirements example is only for Manager.")
    if case == "bad-draft" and role not in {"checker", "all"}:
        raise ModelCallError("Bad-draft example is only for Checker.")
    requirements = requirements or sample_requirements()
    outline = sample_outline(requirements)
    # These are fixture facts for Writer/Checker, not Data Agent's preceding output.
    data = _sample_data(data_root, requirements) if role in {"all", "writer", "checker"} else None
    content = sample_content(outline, data) if data is not None else None
    draft = (
        Draft(**content.model_dump(), markdown=render_draft(content))
        if content is not None
        else None
    )
    if case == "bad-draft":
        content.fact_claims[0].value = 99
        content.sections.pop()
        draft = Draft(**content.model_dump(), markdown=render_draft(content))
    text = user_text or (
        "请写部门汇报。"
        if case == "missing-requirements"
        else f"请为{requirements.department}生成 "
        f"{requirements.start_date} 至 {requirements.end_date}"
        f"（结束日不含）的 Markdown 汇报，章节：{'、'.join(requirements.required_sections)}。"
    )
    runs = []
    for current in ROLES if role == "all" else (role,):
        try:
            if current == "manager":
                output = run_manager(text, session, data_origin=requirements.data_origin)
                status = "passed" if output.status == "ready" else "needs_input"
            elif current == "planner":
                output = run_planner(requirements, session)
                status = "passed"
            elif current == "data":
                output = run_data_agent(requirements, data_root, session)
                status = "passed" if output.status == "ready" else "needs_input"
            elif current == "writer":
                output = run_writer(requirements, outline, data, session)
                status = "passed" if data.status == "ok" else "needs_input"
            else:
                output = run_checker(requirements, outline, data, draft, session)
                status = (
                    "passed"
                    if output.passed
                    else ("needs_input" if output.needs_input else "review_failed")
                )
            runs.append(RoleRun(role=current, status=status, output=output.model_dump(mode="json")))
        except ModelCallError as exc:
            runs.append(RoleRun(role=current, status="failed", error=str(exc)))
        except Exception:
            runs.append(
                RoleRun(role=current, status="failed", error="Independent role execution failed.")
            )
        if runs[-1].status != "passed":
            break
    status = next((run.status for run in runs if run.status != "passed"), "passed")
    return AgentRunReport(
        mode=session.mode,
        status=status,
        runs=runs,
        events=list(session.events),
        request_count=session.request_count,
        reserved_output_tokens=session.reserved_output_tokens,
        usage=session.usage_statistics,
    )
