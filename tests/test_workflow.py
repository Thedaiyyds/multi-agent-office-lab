"""Graph-level propagation, isolation and safe terminal-state tests (no network)."""

from datetime import datetime
from uuid import uuid4

import pytest

import office_agents.workflow as workflow
from office_agents.agent_runtime import AgentSession
from office_agents.config import Settings
from office_agents.llm import ModelCallError
from office_agents.workflow_examples import make_workflow_mock_transport

REQUEST = "生成研发部2026年第二季度工作报告"


@pytest.fixture
def session():
    value = AgentSession(
        Settings(base_url="https://mock.invalid", model="workflow-fixture"),
        mode="offline_mock",
        max_requests=6,
        max_total_output_tokens=1984,
        transport=make_workflow_mock_transport(),
    )
    try:
        yield value
    finally:
        value.close()


def test_actual_graph_outputs_feed_every_following_node_with_consistent_run_id(session):
    run_id = str(uuid4())
    result = workflow.run_workflow(
        REQUEST, "data/samples", session, data_origin="simulated", run_id=run_id
    )
    assert result.status == "completed"
    assert result.request_count == 6
    assert result.reserved_output_tokens == 1984
    assert result.revision_count == 0
    manager, planner, data, writer, checker = result.nodes
    assert planner.input["requirements"] == manager.output["requirements"]
    assert data.input["requirements"] == planner.input["requirements"]
    assert writer.input["outline"] == planner.output
    assert writer.input["data"] == data.output["data"]
    assert checker.input["draft"] == writer.output
    assert checker.input["data"] == data.output["data"]
    assert result.data_result.data.run_id == run_id
    assert {event.run_id for event in result.events} == {run_id}
    assert [node.role for node in result.nodes] == [
        "manager",
        "planner",
        "data",
        "writer",
        "checker",
    ]
    assert [event.role for event in result.events if event.event_type == "model_request"] == [
        "manager",
        "planner",
        "data",
        "data",
        "writer",
        "checker",
    ]
    assert len([event for event in result.events if event.event_type == "tool_execution"]) == 1
    assert result.usage["total_tokens"] is None  # The mock does not invent usage.
    for node in result.nodes:
        assert node.duration_ms >= 0
        assert datetime.fromisoformat(node.finished_at) >= datetime.fromisoformat(node.started_at)
        finish = next(
            event
            for event in result.events
            if event.role == node.role and event.event_type == "node_finished"
        )
        assert finish.duration_ms == node.duration_ms
    assert all(
        event.duration_ms is None
        for event in result.events
        if event.event_type in {"model_request", "tool_execution"}
    )


@pytest.mark.parametrize(
    ("role", "expected_requests"),
    [("manager", 0), ("planner", 1), ("data", 2), ("writer", 4), ("checker", 5)],
)
def test_each_node_exception_retains_prior_outputs_and_never_runs_downstream(
    monkeypatch, session, role, expected_requests
):
    def failed(*args, **kwargs):
        raise ModelCallError("PRIVATE_PROVIDER_BODY_AND_SECRET")

    name = "run_data_agent" if role == "data" else f"run_{role}"
    monkeypatch.setattr(workflow, name, failed)
    result = workflow.run_workflow(REQUEST, "data/samples", session)
    assert result.status == "failed"
    assert result.request_count == expected_requests
    assert result.nodes[-1].role == role
    assert result.nodes[-1].status == "failed"
    assert result.nodes[-1].output is None
    assert all(node.output is not None for node in result.nodes[:-1])
    assert "PRIVATE_PROVIDER_BODY_AND_SECRET" not in result.model_dump_json()
    assert role.capitalize() in result.error
    assert result.events[-1].status == "failed"
    assert result.events[-1].duration_ms is not None


def test_writer_cannot_mutate_authoritative_data_or_its_input_snapshot(monkeypatch, session):
    original = workflow.run_writer

    def mutating_writer(requirements, outline, data, session, **kwargs):
        data.metrics[0].value = 99
        return original(requirements, outline, data, session, **kwargs)

    monkeypatch.setattr(workflow, "run_writer", mutating_writer)
    result = workflow.run_workflow(REQUEST, "data/samples", session, max_revisions=0)
    assert result.status == "review_failed"
    assert result.data_result.data.metrics[0].value == 3
    assert result.metrics[0].value == 3
    assert result.nodes[3].input["data"]["metrics"][0]["value"] == 3
    assert result.draft.fact_claims[0].value == 99
    assert any(issue.code == "fact_value" for issue in result.review.issues)


def test_post_run_mutation_cannot_change_independent_audit_records(session):
    result = workflow.run_workflow(REQUEST, "data/samples", session)
    result.requirements.department = "changed"
    result.outline.sections[0].title = "changed"
    result.data_result.data.metrics[0].value = 99
    result.draft.fact_claims[0].value = 99
    assert result.nodes[1].input["requirements"]["department"] == "研发部"
    assert result.nodes[3].input["outline"]["sections"][0]["title"] == "工作概况"
    assert result.nodes[4].input["data"]["metrics"][0]["value"] == 3
    assert result.nodes[4].input["draft"]["fact_claims"][0]["value"] == 3


def test_reused_session_is_rejected_before_any_additional_request(session):
    workflow.run_workflow(REQUEST, "data/samples", session)
    count = session.request_count
    with pytest.raises(ValueError, match="fresh dedicated"):
        workflow.run_workflow(REQUEST, "data/samples", session)
    assert session.request_count == count


@pytest.mark.parametrize("run_id", ["../escape", "not-a-uuid", str(uuid4()).upper()])
def test_invalid_run_id_fails_before_request(session, run_id):
    with pytest.raises(ValueError):
        workflow.run_workflow(REQUEST, "data/samples", session, run_id=run_id)
    assert session.request_count == 0


def test_malformed_role_contract_becomes_safe_node_failure(monkeypatch, session):
    original = workflow.run_planner

    def malformed(requirements, session):
        output = original(requirements, session)
        output.sections = []  # Assignment validation is off; graph must revalidate output.
        return output

    monkeypatch.setattr(workflow, "run_planner", malformed)
    result = workflow.run_workflow(REQUEST, "data/samples", session)
    assert result.status == "failed"
    assert result.nodes[-1].role == "planner"
    assert result.nodes[-1].output is None
    assert result.data_result is None
    assert result.request_count == 2


@pytest.mark.parametrize(
    ("budget", "limit", "reason"),
    [
        ("max_requests", 1, "request budget exhausted"),
        ("max_total_output_tokens", 300, "output budget exhausted"),
    ],
)
def test_budget_failure_reports_only_known_static_reason(session, budget, limit, reason):
    setattr(session, budget, limit)
    result = workflow.run_workflow(REQUEST, "data/samples", session)
    assert result.status == "failed"
    assert result.nodes[-1].role == "planner"
    assert result.request_count == 1
    assert reason in result.error
    assert result.nodes[-1].error == result.error
    assert result.events[-1].summary == result.error


def test_budget_like_private_exception_cannot_bypass_exact_allowlist(monkeypatch, session):
    def failed(*args, **kwargs):
        raise ModelCallError("Agent request budget exhausted. PRIVATE_PROVIDER_BODY_AND_SECRET")

    monkeypatch.setattr(workflow, "run_manager", failed)
    result = workflow.run_workflow(REQUEST, "data/samples", session)
    assert result.status == "failed"
    assert result.error == "Manager node failed; inspect safe audit events and inputs."
    assert "PRIVATE_PROVIDER_BODY_AND_SECRET" not in result.model_dump_json()


@pytest.mark.parametrize(
    ("role", "message", "diagnosis"),
    [
        (
            "manager",
            "Manager returned invalid or ungrounded requirements.",
            "Manager requirements invalid or ungrounded",
        ),
        (
            "planner",
            "Planner returned an invalid section or metric plan.",
            "Planner section or metric plan invalid",
        ),
    ],
)
def test_requirement_and_plan_validation_have_safe_explicit_diagnoses(
    monkeypatch, session, role, message, diagnosis
):
    def failed(*args, **kwargs):
        raise ModelCallError(message)

    monkeypatch.setattr(workflow, f"run_{role}", failed)
    result = workflow.run_workflow(REQUEST, "data/samples", session)
    assert result.status == "failed"
    assert diagnosis in result.error
    assert result.nodes[-1].error == result.error
