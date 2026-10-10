"""Real-time observers cannot mutate, interrupt or replay the business graph."""

import json
from pathlib import Path

import httpx

from office_agents.agent_runtime import AgentSession
from office_agents.config import Settings
from office_agents.workflow import run_workflow
from office_agents.workflow_examples import workflow_mock_response

SAMPLES = Path(__file__).parents[1] / "data" / "samples"


def test_observer_receives_actual_start_before_http_and_identical_final_events():
    observed = []
    calls = []

    def handler(request):
        payload = json.loads(request.content)
        role = payload["messages"][0]["content"].splitlines()[0].removeprefix("ROLE=")
        assert observed[-1].event_type == "node_started"
        assert observed[-1].role == role
        calls.append(role)
        return workflow_mock_response(request)

    session = AgentSession(
        Settings(base_url="https://mock.invalid", model="observer-fixture"),
        mode="offline_mock",
        max_requests=10,
        max_total_output_tokens=4032,
        transport=httpx.MockTransport(handler),
    )
    try:
        result = run_workflow(
            "生成研发部2026年第二季度工作报告",
            SAMPLES,
            session,
            data_origin="simulated",
            test_scenario="bad-fact",
            on_event=observed.append,
        )
    finally:
        session.close()
    assert result.status == "completed" and len(calls) == 7
    assert observed == result.events
    assert [e.revision_index for e in observed if e.role == "writer" and e.status == "running"] == [
        0,
        1,
    ]


def test_failed_mutating_observer_cannot_modify_audit_or_replay_http():
    def observer(event):
        event.run_id = "PRIVATE_FAKE_RUN"
        event.status = "failed"
        raise RuntimeError("PRIVATE_UI_ERROR")

    session = AgentSession(
        Settings(base_url="https://mock.invalid", model="observer-fixture"),
        mode="offline_mock",
        max_requests=6,
        max_total_output_tokens=1984,
        transport=httpx.MockTransport(workflow_mock_response),
    )
    try:
        result = run_workflow(
            "生成研发部2026年第二季度工作报告", SAMPLES, session, on_event=observer
        )
    finally:
        session.close()
    assert result.status == "completed" and result.request_count == 6
    assert all(event.run_id == result.run_id for event in result.events)
    assert "PRIVATE_" not in result.model_dump_json()
