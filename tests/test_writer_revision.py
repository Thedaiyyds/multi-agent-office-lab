"""Actual HTTP context carries the rejected draft and actionable feedback."""

import json
from pathlib import Path

import httpx
import pytest

from office_agents.agent_examples import sample_content, sample_outline, sample_requirements
from office_agents.agent_runtime import AgentSession
from office_agents.agent_schemas import Draft, Review, ReviewIssue
from office_agents.agents.writer import allowed_section_texts, render_draft, run_writer
from office_agents.config import Settings
from office_agents.llm import ModelCallError
from office_agents.schemas import DataRequest
from office_agents.tools.metrics import run_data_tools


def test_revision_passes_actual_prior_draft_and_program_feedback_over_http():
    requirements = sample_requirements()
    outline = sample_outline(requirements)
    data = run_data_tools(
        Path(__file__).resolve().parents[1] / "data" / "samples",
        DataRequest(
            department=requirements.department,
            start_date=requirements.start_date,
            end_date=requirements.end_date,
            data_origin=requirements.data_origin,
        ),
    )
    content = sample_content(outline, data)
    for section in content.sections:
        section.text = allowed_section_texts(outline)[section.section_id]
    previous = Draft(**content.model_dump(), markdown=render_draft(content))
    previous.fact_claims[0].value = 99
    previous.markdown = render_draft(previous)
    review = Review(
        passed=False,
        issues=[
            ReviewIssue(
                code="fact_value",
                location="fact_claims[0]",
                message="事实值与权威数据不一致。",
            )
        ],
        revision_instructions=["请将项目数改为权威 metrics 的值，保持来源不变。"],
    )
    captured = []

    def handler(request):
        captured.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": content.model_dump_json(),
                        },
                    }
                ]
            },
        )

    session = AgentSession(
        Settings(base_url="https://mock.invalid", model="fixture"),
        mode="offline_mock",
        transport=httpx.MockTransport(handler),
    )
    try:
        first = run_writer(requirements, outline, data, session, strict_narrative=True)
        second = run_writer(
            requirements,
            outline,
            data,
            session,
            previous_draft=previous,
            review=review,
            strict_narrative=True,
        )
    finally:
        session.close()
    first_context = json.loads(captured[0]["messages"][1]["content"])
    second_context = json.loads(captured[1]["messages"][1]["content"])
    assert first_context["previous_draft"] is None and first_context["review"] is None
    assert second_context["previous_draft"] == previous.model_dump(
        mode="json", exclude={"markdown"}
    )
    assert second_context["previous_draft"]["fact_claims"][0]["value"] == 99
    assert second_context["review"] == review.model_dump(mode="json")
    assert "markdown" not in second_context["previous_draft"]
    assert second_context["metrics"][0]["value"] == 3
    assert second_context["allowed_section_texts"] == allowed_section_texts(outline)
    assert first == second and second.fact_claims[0].value == 3
    assert previous.fact_claims[0].value == 99
    assert session.request_count == 2
    assert all(item["max_tokens"] == 768 for item in captured)


@pytest.mark.parametrize("missing", ["draft", "review"])
def test_partial_revision_context_rejected_before_http(missing):
    requirements = sample_requirements()
    outline = sample_outline(requirements)
    data = run_data_tools(
        Path(__file__).resolve().parents[1] / "data" / "samples",
        DataRequest(
            department=requirements.department,
            start_date=requirements.start_date,
            end_date=requirements.end_date,
            data_origin=requirements.data_origin,
        ),
    )
    content = sample_content(outline, data)
    previous = Draft(**content.model_dump(), markdown=render_draft(content))
    review = Review(passed=False, revision_instructions=["修正指标。"])

    def handler(request):
        pytest.fail("Malformed revision context must not trigger HTTP")

    session = AgentSession(
        Settings(base_url="https://mock.invalid", model="fixture"),
        mode="offline_mock",
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(ModelCallError, match="requires both"):
            run_writer(
                requirements,
                outline,
                data,
                session,
                previous_draft=None if missing == "draft" else previous,
                review=None if missing == "review" else review,
                strict_narrative=True,
            )
        assert session.request_count == 0
    finally:
        session.close()
