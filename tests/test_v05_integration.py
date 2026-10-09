"""Independent HTTP-level acceptance of repair, grounding, retries and immutable data."""

import json
from pathlib import Path

import httpx
import pytest

from office_agents.agent_runtime import AgentSession
from office_agents.config import Settings
from office_agents.workflow import run_workflow
from office_agents.workflow_examples import workflow_mock_response
from office_agents.workflow_export import save_workflow

SAMPLES = Path(__file__).parents[1] / "data" / "samples"
REQUEST = "生成研发部2026年第二季度工作报告"


def role(payload):
    return payload["messages"][0]["content"].splitlines()[0].removeprefix("ROLE=")


def context(payload):
    return json.loads(
        next(item["content"] for item in payload["messages"] if item["role"] == "user")
    )


def edit_response(response, edit):
    body = response.json()
    content = json.loads(body["choices"][0]["message"]["content"])
    edit(content)
    body["choices"][0]["message"]["content"] = json.dumps(content, ensure_ascii=False)
    return httpx.Response(200, json=body)


def execute(
    *,
    scenario="none",
    revisions=2,
    retries=0,
    mutate=None,
    requests=12,
    output=5568,
    user_text=REQUEST,
    data_root=SAMPLES,
):
    calls = []

    def handler(request):
        payload = json.loads(request.content)
        calls.append(payload)
        response = workflow_mock_response(request)
        return mutate(payload, response) if mutate else response

    session = AgentSession(
        Settings(base_url="https://mock.invalid", model="v05-script", api_key="v05-private-key"),
        mode="offline_mock",
        max_requests=requests,
        max_total_output_tokens=output,
        retry_budget=retries,
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    )
    try:
        result = run_workflow(
            user_text,
            data_root,
            session,
            data_origin="simulated",
            max_revisions=revisions,
            test_scenario=scenario,
        )
        return result, calls
    finally:
        session.close()


@pytest.mark.parametrize("scenario", ["bad-fact", "missing-section"])
def test_real_writer_feedback_and_auditable_injection_repair(scenario, tmp_path):
    result, calls = execute(scenario=scenario)
    assert result.status == "completed" and result.revision_count == 1
    assert result.request_count == result.logical_request_count == 7
    assert result.retry_count == 0 and result.test_scenario == scenario
    assert [role(item) for item in calls] == [
        "manager",
        "planner",
        "data",
        "data",
        "writer",
        "writer",
        "checker",
    ]
    first, corrected = result.revision_history
    assert not first.review.passed and first.review_mode == "program_only"
    assert corrected.review.passed and corrected.review_mode == "program_and_model"
    feedback = context(calls[5])
    assert feedback["previous_draft"] == first.draft.model_dump(mode="json", exclude={"markdown"})
    assert feedback["review"] == first.review.model_dump(mode="json")
    assert feedback["review"]["issues"] and feedback["review"]["revision_instructions"]
    initial_writer = result.nodes[first.writer_node_index]
    assert initial_writer.generated_output is not None
    assert initial_writer.generated_output != initial_writer.output
    assert initial_writer.output == first.draft.model_dump(mode="json")
    assert result.nodes[corrected.writer_node_index].output == corrected.draft.model_dump(
        mode="json"
    )
    assert [m.value for m in result.metrics] == [3, 2, 2 / 3, 2]
    authoritative = result.data_result.data.model_dump(mode="json")
    for node in result.nodes:
        if node.role in {"writer", "checker"}:
            assert node.input["data"] == authoritative
    assert len([e for e in result.events if e.event_type == "error_injected"]) == 1
    directory = save_workflow(result, tmp_path)
    assert (directory / "report.md").exists()
    for index, record in enumerate(result.revision_history):
        folder = directory / "revisions" / f"{index:02d}"
        assert record.draft.markdown in (folder / "draft.md").read_text()
        assert json.loads((folder / "review.json").read_text()) == record.review.model_dump(
            mode="json"
        )
    assert "v05-private-key" not in (directory / "run.json").read_text()


@pytest.mark.parametrize("limit", [0, 1, 2])
def test_persistent_fault_stops_at_actual_revision_limit(limit, tmp_path):
    result, calls = execute(scenario="always-bad", revisions=limit)
    assert result.status == "review_failed" and result.revision_count == limit
    assert len(result.revision_history) == limit + 1
    assert len([n for n in result.nodes if n.role == "writer"]) == limit + 1
    assert len(calls) == 5 + limit
    assert all(
        not r.review.passed and r.review_mode == "program_only" for r in result.revision_history
    )
    assert result.data_result.data.metrics == result.metrics
    assert [m.value for m in result.metrics] == [3, 2, 2 / 3, 2]
    directory = save_workflow(result, tmp_path)
    assert not (directory / "report.md").exists()
    assert "审核未通过" in (directory / "draft.md").read_text()


@pytest.mark.parametrize("unsafe", ["项目数为99，完成率100%。", "资源紧张，所有工作按计划完成。"])
def test_ungrounded_prose_is_rejected_then_repaired_without_numeric_rewriting(unsafe):
    writer_count = 0

    def mutate(payload, response):
        nonlocal writer_count
        if role(payload) == "writer":
            writer_count += 1
            if writer_count == 1:
                return edit_response(
                    response, lambda draft: draft["sections"][0].update(text=unsafe)
                )
        return response

    result, calls = execute(mutate=mutate)
    assert result.status == "completed" and result.revision_count == 1
    first = result.revision_history[0]
    assert first.draft.sections[0].text == unsafe and not first.review.passed
    assert first.review_mode == "program_only"
    assert unsafe not in result.draft.markdown
    assert [m.value for m in result.metrics] == [3, 2, 2 / 3, 2]
    assert role(calls[-1]) == "checker"  # Only corrected draft reaches model review.


def test_model_semantic_rejection_also_routes_real_feedback_to_writer():
    checker_count = 0

    def mutate(payload, response):
        nonlocal checker_count
        if role(payload) == "checker":
            checker_count += 1
            if checker_count == 1:
                return edit_response(
                    response,
                    lambda review: review.update(
                        passed=False,
                        issues=[
                            {
                                "code": "proposal",
                                "location": "suggestions",
                                "message": "建议应更具体。",
                                "severity": "warning",
                            }
                        ],
                        revision_instructions=["补充清晰的未来行动建议。"],
                    ),
                )
        return response

    result, calls = execute(mutate=mutate)
    assert result.status == "completed" and result.revision_count == 1
    assert result.request_count == 8
    assert all(r.review_mode == "program_and_model" for r in result.revision_history)
    assert context(calls[-2])["review"]["revision_instructions"] == ["补充清晰的未来行动建议。"]


@pytest.mark.parametrize("transient", ["timeout", "http"])
def test_network_retry_counts_do_not_become_business_revisions(transient):
    first = True

    def mutate(payload, response):
        nonlocal first
        if role(payload) == "manager" and first:
            first = False
            if transient == "timeout":
                raise httpx.ReadTimeout("v05-private-provider-content")
            return httpx.Response(503, text="v05-private-provider-content")
        return response

    result, calls = execute(retries=1, mutate=mutate)
    assert result.status == "completed" and result.retry_count == 1
    assert result.revision_count == 0 and len(result.revision_history) == 1
    assert len(calls) == result.request_count == 7 and result.logical_request_count == 6
    assert result.reserved_output_tokens == 2240
    assert len([e for e in result.events if e.event_type == "model_retry"]) == 1
    assert "v05-private-provider-content" not in result.model_dump_json()


def test_exhausted_global_retry_and_per_logical_limit_stop_safely(tmp_path):
    def mutate(payload, response):
        return httpx.Response(503, text="v05-private-service-body")

    result, calls = execute(retries=2, mutate=mutate)
    assert result.status == "failed" and len(calls) == 2
    assert result.retry_count == 1 and result.logical_request_count == 1
    assert result.revision_count == 0 and not result.revision_history
    assert "v05-private-service-body" not in result.model_dump_json()
    assert not (save_workflow(result, tmp_path) / "report.md").exists()


def test_budget_failure_preserves_corrected_but_unreviewed_draft(tmp_path):
    result, calls = execute(scenario="bad-fact", requests=6)
    assert result.status == "failed" and result.revision_count == 1 and len(calls) == 6
    assert len(result.revision_history) == 1 and not result.revision_history[0].review.passed
    assert result.draft.fact_claims[0].value == 3
    assert result.nodes[-1].role == "checker" and result.nodes[-1].status == "failed"
    directory = save_workflow(result, tmp_path)
    assert not (directory / "report.md").exists()
    assert result.draft.markdown in (directory / "draft.md").read_text()


def test_missing_data_does_not_enter_revision_loop(tmp_path):
    result, calls = execute(data_root=tmp_path)
    assert result.status == "needs_input" and result.revision_count == 0
    assert not result.revision_history and len(calls) == 3
    assert not any(node.role in {"writer", "checker"} for node in result.nodes)
