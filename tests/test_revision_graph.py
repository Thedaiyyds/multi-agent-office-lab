"""Actual cyclic graph, mutation boundaries and repeated audit export checks."""

import json

import httpx
import pytest

import office_agents.workflow as workflow
from office_agents.agent_runtime import AgentSession
from office_agents.config import Settings
from office_agents.llm import ModelCallError
from office_agents.workflow_examples import workflow_mock_response
from office_agents.workflow_export import WorkflowExportError, save_workflow

REQUEST = "生成研发部2026年第二季度工作报告"


def run_case(
    case="none", *, revisions=2, handler=workflow_mock_response, budget=10, request=REQUEST
):
    session = AgentSession(
        Settings(base_url="https://mock.invalid", model="revision-fixture"),
        mode="offline_mock",
        max_requests=budget,
        max_total_output_tokens=4032,
        transport=httpx.MockTransport(handler),
    )
    try:
        return workflow.run_workflow(
            request,
            "data/samples",
            session,
            data_origin="simulated",
            test_scenario=case,
            max_revisions=revisions,
        )
    finally:
        session.close()


@pytest.mark.parametrize("case", ["bad-fact", "missing-section"])
def test_rejected_first_draft_reaches_actual_writer_with_feedback_then_passes(case, tmp_path):
    contexts = []

    def handler(request):
        payload = json.loads(request.content)
        if payload["messages"][0]["content"].startswith("ROLE=writer"):
            contexts.append(json.loads(payload["messages"][1]["content"]))
        return workflow_mock_response(request)

    result = run_case(case, handler=handler)
    assert result.status == "completed"
    assert result.revision_count == 1
    assert result.request_count == 7
    assert result.logical_request_count == 7
    assert result.retry_count == 0
    assert [node.role for node in result.nodes] == [
        "manager",
        "planner",
        "data",
        "writer",
        "checker",
        "writer",
        "checker",
    ]
    rejected, accepted = result.revision_history
    assert rejected.review_mode == "program_only"
    assert accepted.review_mode == "program_and_model"
    assert not rejected.review.passed and accepted.review.passed
    assert contexts[0]["previous_draft"] is None
    assert contexts[1]["previous_draft"] == rejected.draft.model_dump(
        mode="json", exclude={"markdown"}
    )
    assert contexts[1]["review"] == rejected.review.model_dump(mode="json")
    assert contexts[0]["metrics"] == contexts[1]["metrics"]
    assert result.nodes[3].generated_output != result.nodes[3].output
    assert result.nodes[5].generated_output is None
    assert result.nodes[3].input["data"] == result.nodes[5].input["data"]
    assert result.nodes[4].input["data"] == result.nodes[6].input["data"]
    assert result.metrics[0].value == 3
    assert sum(event.event_type == "error_injected" for event in result.events) == 1
    assert [
        event.revision_index for event in result.events if event.event_type == "node_started"
    ] == [0, 0, 0, 0, 0, 1, 1]
    directory = save_workflow(result, tmp_path)
    assert (directory / "report.md").exists()
    for revision in result.revision_history:
        root = directory / "revisions" / f"{revision.revision_index:02d}"
        assert revision.draft.markdown in (root / "draft.md").read_text()
        assert json.loads((root / "review.json").read_text()) == revision.review.model_dump(
            mode="json"
        )


@pytest.mark.parametrize("limit", [0, 1, 2])
def test_continuous_errors_stop_at_exact_revision_limit_and_preserve_all_failed_rounds(
    limit, tmp_path
):
    result = run_case("always-bad", revisions=limit)
    assert result.status == "review_failed"
    assert result.revision_count == limit
    assert len(result.revision_history) == limit + 1
    assert result.request_count == 5 + limit
    assert len(result.nodes) == 5 + limit * 2
    assert all(not record.review.passed for record in result.revision_history)
    assert all(record.review_mode == "program_only" for record in result.revision_history)
    assert all(
        node.input["data"]["metrics"][0]["value"] == 3
        for node in result.nodes
        if node.role in {"writer", "checker"}
    )
    assert all(record.draft.fact_claims[0].value == 4 for record in result.revision_history)
    directory = save_workflow(result, tmp_path)
    assert not (directory / "report.md").exists()
    assert "审核未通过" in (directory / "draft.md").read_text()
    assert len(list((directory / "revisions").iterdir())) == limit + 1


def test_revised_writer_failure_preserves_original_checked_draft_and_actual_failed_node(
    monkeypatch, tmp_path
):
    original = workflow.run_writer

    def writer(*args, **kwargs):
        if kwargs.get("previous_draft") is not None:
            raise ModelCallError("PRIVATE_SECRET_RAW_BODY")
        return original(*args, **kwargs)

    monkeypatch.setattr(workflow, "run_writer", writer)
    result = run_case("bad-fact")
    assert result.status == "failed"
    assert len(result.revision_history) == 1
    assert result.nodes[-1].role == "writer" and result.nodes[-1].status == "failed"
    assert result.nodes[-1].revision_index == 1
    assert result.draft == result.revision_history[0].draft
    assert "PRIVATE_SECRET_RAW_BODY" not in result.model_dump_json()
    directory = save_workflow(result, tmp_path)
    assert (directory / "revisions/00/review.json").exists()
    assert not (directory / "report.md").exists()


def test_request_budget_can_fail_during_revision_without_erasing_prior_review(tmp_path):
    result = run_case("bad-fact", budget=5)
    assert result.status == "failed"
    assert result.request_count == 5
    assert result.nodes[-1].role == "writer"
    assert result.revision_history[0].review_mode == "program_only"
    assert not result.revision_history[0].review.passed
    directory = save_workflow(result, tmp_path)
    assert not (directory / "report.md").exists()


def test_checker_needs_input_stops_before_any_revision(monkeypatch):
    from office_agents.agent_schemas import Review

    def checker(*args, **kwargs):
        return Review(passed=False, needs_input=True, revision_instructions=["人工补充材料。"])

    monkeypatch.setattr(workflow, "run_checker", checker)
    result = run_case()
    assert result.status == "needs_input"
    assert result.revision_count == 0
    assert len(result.nodes) == 5
    assert len(result.revision_history) == 1


def test_single_section_missing_experiment_stays_valid_contract_then_recovers():
    result = run_case("missing-section", request=REQUEST + "；章节：工作概况")
    assert result.status == "completed"
    assert result.revision_count == 1
    assert result.revision_history[0].draft.sections[0].title == "实验注入的缺失章节"
    assert result.draft.sections[0].title == "工作概况"


@pytest.mark.parametrize(
    "tamper",
    [
        "earlier_data",
        "earlier_draft",
        "earlier_review",
        "generated",
        "history_index",
        "node_index",
        "review_mode",
        "previous",
        "extra_node",
        "injection_flag",
        "strict_policy",
    ],
)
def test_final_export_gate_checks_entire_revision_history(tamper, tmp_path):
    result = run_case("bad-fact")
    if tamper == "earlier_data":
        result.nodes[3].input["data"]["metrics"][0]["value"] = 4
    elif tamper == "earlier_draft":
        result.revision_history[0].draft.fact_claims[0].value = 33
    elif tamper == "earlier_review":
        result.nodes[4].output = {"passed": True}
    elif tamper == "generated":
        result.nodes[3].generated_output["fact_claims"][0]["value"] = 33
    elif tamper == "history_index":
        result.revision_history[0].revision_index = 1
    elif tamper == "node_index":
        result.revision_history[0].checker_node_index = 6
    elif tamper == "review_mode":
        result.revision_history[0].review_mode = "program_and_model"
    elif tamper == "previous":
        result.nodes[5].input["previous_draft"] = None
    elif tamper == "extra_node":
        result.nodes.append(result.nodes[-1].model_copy(deep=True))
    elif tamper == "injection_flag":
        result.test_scenario = "none"
    else:
        result.nodes[5].input["strict_narrative"] = False
    with pytest.raises(WorkflowExportError):
        save_workflow(result, tmp_path)
    assert not (tmp_path / result.run_id / "report.md").exists()


@pytest.mark.parametrize(
    "tamper",
    [
        "request_count",
        "logical_count",
        "reservation",
        "retry_count",
        "failed_checker",
        "missing_request",
        "missing_cap",
    ],
)
def test_final_export_rechecks_actual_model_attempt_accounting(tamper, tmp_path):
    result = run_case()
    checker = next(
        event
        for event in result.events
        if event.role == "checker" and event.event_type == "model_request"
    )
    if tamper == "request_count":
        result.request_count += 1
    elif tamper == "logical_count":
        result.logical_request_count += 1
    elif tamper == "reservation":
        result.reserved_output_tokens += 1
    elif tamper == "retry_count":
        result.retry_budget = 1
        result.retry_count = 1
    elif tamper == "failed_checker":
        checker.status = "failed"
    elif tamper == "missing_request":
        result.events.remove(checker)
    else:
        checker.max_output_tokens = None
    with pytest.raises(WorkflowExportError, match="local validation"):
        save_workflow(result, tmp_path)
    assert not (tmp_path / result.run_id / "report.md").exists()


def test_successful_network_retry_is_separate_from_business_revision_and_exportable(tmp_path):
    attempts = 0

    def handler(request):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503)
        return workflow_mock_response(request)

    session = AgentSession(
        Settings(base_url="https://mock.invalid", model="retry-fixture"),
        mode="offline_mock",
        max_requests=7,
        max_total_output_tokens=2240,
        retry_budget=1,
        transport=httpx.MockTransport(handler),
    )
    try:
        result = workflow.run_workflow(REQUEST, "data/samples", session, data_origin="simulated")
    finally:
        session.close()
    assert result.status == "completed"
    assert result.request_count == 7 and result.logical_request_count == 6
    assert result.retry_count == 1 and result.revision_count == 0
    assert (save_workflow(result, tmp_path) / "report.md").exists()


@pytest.mark.parametrize(("case", "budget", "revision_index"), [("none", 5, 0), ("bad-fact", 6, 1)])
def test_checker_failure_preserves_actual_unreviewed_writer_version_without_fake_review(
    tmp_path, case, budget, revision_index
):
    result = run_case(case, budget=budget)
    assert result.status == "failed"
    assert result.nodes[-1].role == "checker" and result.nodes[-1].status == "failed"
    assert result.nodes[-2].role == "writer" and result.nodes[-2].status == "passed"
    assert result.nodes[-2].revision_index == revision_index
    assert len(result.revision_history) == revision_index
    directory = save_workflow(result, tmp_path)
    pending = directory / "revisions" / f"{revision_index:02d}"
    assert result.draft.markdown in (pending / "draft.md").read_text()
    assert "待审核，Checker 未完成" in (pending / "draft.md").read_text()
    assert not (pending / "review.json").exists()
    assert not (directory / "report.md").exists()
    for checked in result.revision_history:
        earlier = directory / "revisions" / f"{checked.revision_index:02d}"
        assert json.loads((earlier / "review.json").read_text()) == checked.review.model_dump(
            mode="json"
        )
