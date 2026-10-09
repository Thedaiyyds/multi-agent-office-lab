"""Capture actual HTTP context: local date hints aid parsing without guessing."""

import json
from datetime import date

import httpx
import pytest

from office_agents.agent_runtime import AgentSession
from office_agents.agents.manager import _date_range_is_grounded, run_manager
from office_agents.config import Settings
from office_agents.llm import ModelCallError
from office_agents.workflow_examples import workflow_mock_response


@pytest.mark.parametrize(
    ("user_text", "hints", "status"),
    [
        (
            "生成研发部2026年第二季度工作报告",
            [{"start_date": "2026-04-01", "end_date": "2026-07-01"}],
            "ready",
        ),
        (
            "生成研发部2026年第四季度工作报告",
            [{"start_date": "2026-10-01", "end_date": "2027-01-01"}],
            "ready",
        ),
        (
            "生成研发部2026-04-01至2026-07-01工作报告",
            [{"start_date": "2026-04-01", "end_date": "2026-07-01"}],
            "ready",
        ),
        ("生成研发部第二季度工作报告", [], "needs_input"),
    ],
)
def test_model_receives_grounded_ranges_without_current_year_guess(user_text, hints, status):
    contexts = []

    def capture(http_request):
        payload = json.loads(http_request.content)
        contexts.append(json.loads(payload["messages"][1]["content"]))
        assert "季度 end_date 是下季度第一天（不含）" in payload["messages"][0]["content"]
        return workflow_mock_response(http_request)

    session = AgentSession(
        Settings(base_url="https://mock.invalid", model="manager-hints-fixture"),
        mode="offline_mock",
        max_requests=1,
        transport=httpx.MockTransport(capture),
    )
    try:
        result = run_manager(user_text, session)
        assert result.status == status
        assert contexts[0]["user_text"] == user_text
        assert contexts[0]["grounded_date_ranges"] == hints
        assert session.request_count == 1
    finally:
        session.close()


def test_hint_does_not_correct_wrong_model_quarter_end():
    def wrong_end(http_request):
        response = workflow_mock_response(http_request)
        payload = response.json()
        output = json.loads(payload["choices"][0]["message"]["content"])
        output["requirements"]["end_date"] = "2026-06-30"
        payload["choices"][0]["message"]["content"] = json.dumps(output, ensure_ascii=False)
        return httpx.Response(200, json=payload)

    session = AgentSession(
        Settings(base_url="https://mock.invalid", model="manager-hints-fixture"),
        mode="offline_mock",
        max_requests=1,
        transport=httpx.MockTransport(wrong_end),
    )
    try:
        with pytest.raises(ModelCallError, match="invalid or ungrounded requirements"):
            run_manager("生成研发部2026年第二季度工作报告", session)
        assert session.request_count == 1
        assert session.events[-1].status == "passed"  # HTTP valid; grounding rejected afterward.
    finally:
        session.close()


def test_grounding_keeps_explicit_date_set_semantics_beyond_adjacent_hints():
    assert _date_range_is_grounded(
        "研发部范围可用2026-04-01、2026-05-01、2026-07-01",
        date(2026, 4, 1),
        date(2026, 7, 1),
    )
