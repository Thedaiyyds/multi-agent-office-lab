"""Independent HTTP-level acceptance of the actual five-role data flow."""

import json
import shutil
from pathlib import Path

import httpx
import pytest

from office_agents.agent_runtime import AgentSession
from office_agents.config import Settings
from office_agents.workflow import run_workflow
from office_agents.workflow_examples import workflow_mock_response
from office_agents.workflow_export import save_workflow

SAMPLES = Path(__file__).parents[1] / "data" / "samples"
Q2 = "生成研发部2026年第二季度工作报告"


def role_of(payload):
    return payload["messages"][0]["content"].splitlines()[0].removeprefix("ROLE=")


def user_context(payload):
    user = next(message for message in payload["messages"] if message["role"] == "user")
    return json.loads(user["content"])


def execute(
    request=Q2, *, data_root=SAMPLES, mutate=None, budget=6, origin="simulated", revisions=2
):
    calls = []

    def handler(http_request):
        payload = json.loads(http_request.content)
        calls.append(payload)
        response = workflow_mock_response(http_request)
        return mutate(payload, response) if mutate else response

    session = AgentSession(
        Settings(base_url="https://mock.invalid", model="dynamic-fixture", api_key="sentinel-key"),
        mode="offline_mock",
        transport=httpx.MockTransport(handler),
        max_requests=budget,
        max_total_output_tokens=1984,
    )
    try:
        result = run_workflow(
            request, data_root, session, data_origin=origin, max_revisions=revisions
        )
        return result, calls
    finally:
        session.close()


def change_completion(response, edit):
    payload = response.json()
    content = json.loads(payload["choices"][0]["message"]["content"])
    edit(content)
    payload["choices"][0]["message"]["content"] = json.dumps(content, ensure_ascii=False)
    return httpx.Response(200, json=payload)


@pytest.mark.parametrize(
    ("user_text", "department", "start", "expected"),
    [
        (Q2, "研发部", "2026-04-01", [3, 2, 2 / 3, 2]),
        ("生成研发部2026年第一季度工作报告", "研发部", "2026-01-01", [2, 1, 0.5, 1]),
        ("生成市场部2026年第二季度工作报告", "市场部", "2026-04-01", [1, 0, 0.0, 1]),
    ],
)
def test_requirements_outline_and_actual_data_drive_every_downstream_node(
    user_text, department, start, expected, tmp_path
):
    result, calls = execute(user_text)
    assert result.status == "completed"
    assert result.mode == "offline_mock"
    assert result.request_count == len(calls) == 6
    assert result.reserved_output_tokens == 1984
    assert result.revision_count == 0
    assert [role_of(call) for call in calls] == [
        "manager",
        "planner",
        "data",
        "data",
        "writer",
        "checker",
    ]
    assert result.requirements.department == department
    assert result.requirements.start_date.isoformat() == start
    assert [metric.value for metric in result.metrics] == pytest.approx(expected)
    assert result.data_result.data.request.data_origin == "simulated"
    assert user_context(calls[1])["requirements"] == result.requirements.model_dump(mode="json")
    outline = result.outline.model_dump(mode="json")
    assert [section.section_id for section in result.outline.sections] == [
        "part_1",
        "part_2",
        "part_3",
        "part_4",
    ]
    assert user_context(calls[4])["outline"] == outline
    assert user_context(calls[5])["outline"] == outline
    assert user_context(calls[5])["draft"] == result.draft.model_dump(exclude={"markdown"})
    assert [fact.value for fact in result.draft.fact_claims] == pytest.approx(expected)
    assert user_context(calls[4])["metrics"] == user_context(calls[5])["metrics"]
    assert [node.role for node in result.nodes] == [
        "manager",
        "planner",
        "data",
        "writer",
        "checker",
    ]
    assert result.nodes[1].input["requirements"] == result.nodes[0].output["requirements"]
    assert result.nodes[3].input["outline"] == result.nodes[1].output
    assert result.nodes[3].input["data"] == result.nodes[2].output["data"]
    assert result.nodes[4].input["draft"] == result.nodes[3].output
    lifecycle = [event for event in result.events if event.event_type.startswith("node_")]
    assert [(event.role, event.event_type) for event in lifecycle] == [
        (role, kind)
        for role in ["manager", "planner", "data", "writer", "checker"]
        for kind in ["node_started", "node_finished"]
    ]
    assert all(event.run_id == result.run_id for event in result.events)
    assert len([event for event in result.events if event.event_type == "tool_execution"]) == 1
    assert all(node.duration_ms >= 0 for node in result.nodes)
    destination = save_workflow(result, tmp_path)
    assert (destination / "report.md").is_file()
    assert "sentinel-key" not in (destination / "run.json").read_text()


def test_custom_sections_and_explicit_dates_are_not_replaced_by_default_examples():
    request = "部门：市场部 时间范围2026-04-01到2026-07-01 章节：概况,成果,风险,计划"
    result, calls = execute(request, origin="provided")
    assert result.status == "completed"
    assert result.requirements.required_sections == ["概况", "成果", "风险", "计划"]
    assert (
        result.requirements.data_origin == result.data_result.data.request.data_origin == "provided"
    )
    assert [section.title for section in result.draft.sections] == ["概况", "成果", "风险", "计划"]
    assert user_context(calls[4])["requirements"]["data_origin"] == "provided"


@pytest.mark.parametrize(
    "user_text", ["生成季度工作报告", "生成研发部工作报告", "生成2026年Q2报告"]
)
def test_missing_requirements_stop_before_planner(user_text, tmp_path):
    result, calls = execute(user_text)
    assert result.status == "needs_input"
    assert [role_of(call) for call in calls] == ["manager"]
    assert result.manager_decision.questions
    assert result.draft is result.review is None
    destination = save_workflow(result, tmp_path)
    assert not (destination / "report.md").exists()


@pytest.mark.parametrize("kind", ["no_data", "missing_files"])
def test_data_failure_preserves_actual_issues_and_stops_before_writer(kind, tmp_path):
    request = "生成财务部2026年Q2报告" if kind == "no_data" else Q2
    result, calls = execute(request, data_root=SAMPLES if kind == "no_data" else tmp_path)
    assert result.status == "needs_input"
    assert [node.role for node in result.nodes] == ["manager", "planner", "data"]
    assert not any(role_of(call) in {"writer", "checker"} for call in calls)
    assert result.data_result.data.status == ("no_data" if kind == "no_data" else "invalid_data")
    assert result.data_issues
    assert result.draft is None
    destination = save_workflow(result, tmp_path / "runs")
    assert not (destination / "report.md").exists()


@pytest.mark.parametrize("bad", ["fact_value", "sections_mismatch"])
def test_model_approval_cannot_override_program_audit(bad, tmp_path):
    def mutate(payload, response):
        if role_of(payload) != "writer":
            return response

        def edit(content):
            if bad == "fact_value":
                content["fact_claims"][0]["value"] = 99
            else:
                content["sections"].pop()

        return change_completion(response, edit)

    result, calls = execute(mutate=mutate, revisions=0)
    assert result.status == "review_failed"
    assert result.review.passed is False
    assert bad in {issue.code for issue in result.review.issues}
    assert role_of(calls[-1]) == "writer"  # Program rejection requires no model review.
    assert result.revision_history[-1].review_mode == "program_only"
    assert result.revision_count == 0
    destination = save_workflow(result, tmp_path)
    assert not (destination / "report.md").exists()
    assert "审核未通过" in (destination / "draft.md").read_text()


@pytest.mark.parametrize("failure", ["http", "json", "timeout"])
def test_failed_model_node_stops_and_redacts_provider_content(failure, tmp_path):
    def mutate(payload, response):
        if role_of(payload) != "planner":
            return response
        if failure == "http":
            return httpx.Response(503, text="sentinel-private-provider-error")
        if failure == "timeout":
            raise httpx.ReadTimeout("sentinel-private-provider-error")
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "sentinel-private-provider-error"}}]}
        )

    result, calls = execute(mutate=mutate)
    assert result.status == "failed"
    assert [role_of(call) for call in calls] == ["manager", "planner"]
    assert result.draft is None
    assert "sentinel-private-provider-error" not in result.model_dump_json()
    destination = save_workflow(result, tmp_path)
    assert not (destination / "report.md").exists()


def test_request_budget_stops_before_more_http_and_preserves_completed_nodes(tmp_path):
    result, calls = execute(budget=2)
    assert result.status == "failed"
    assert len(calls) == result.request_count == 2
    assert [node.role for node in result.nodes] == ["manager", "planner", "data"]
    assert result.nodes[-1].status == "failed"
    destination = save_workflow(result, tmp_path)
    assert not (destination / "report.md").exists()


def test_mock_workflow_never_loads_environment_configuration(monkeypatch):
    def forbid():
        raise AssertionError("Offline execution must not load .env credentials")

    monkeypatch.setattr(Settings, "from_env", forbid)
    result, _ = execute()
    assert result.status == "completed"


def test_changes_in_actual_csv_change_writer_facts_and_report(tmp_path):
    data_root = tmp_path / "changed_data"
    shutil.copytree(SAMPLES, data_root)
    project_file = data_root / "projects.csv"
    project_file.write_text(
        project_file.read_text().replace(
            "P003,研发部,2026-06-30,active,75", "P003,研发部,2026-06-30,completed,100"
        )
    )
    result, calls = execute(data_root=data_root, origin="provided")
    assert result.status == "completed"
    assert [metric.value for metric in result.metrics] == [3, 3, 1.0, 2]
    assert [fact.value for fact in result.draft.fact_claims] == [3, 3, 1.0, 2]
    assert user_context(calls[4])["metrics"][1]["value"] == 3
    destination = save_workflow(result, tmp_path / "runs")
    assert "完成项目数 = 3" in (destination / "report.md").read_text()


@pytest.mark.parametrize("change", ["department", "dates", "path"])
def test_model_tool_arguments_cannot_broaden_scope_or_choose_path(change, tmp_path):
    def mutate(payload, response):
        if role_of(payload) != "data":
            return response
        body = response.json()
        function = body["choices"][0]["message"]["tool_calls"][0]["function"]
        arguments = json.loads(function["arguments"])
        if change == "department":
            arguments["department"] = "市场部"
        elif change == "dates":
            arguments["start_date"] = "2026-01-01"
        else:
            arguments["path"] = "sentinel-private-path"
        function["arguments"] = json.dumps(arguments)
        return httpx.Response(200, json=body)

    result, calls = execute(mutate=mutate)
    assert result.status == "failed"
    assert [role_of(call) for call in calls] == ["manager", "planner", "data"]
    assert not any(event.event_type == "tool_execution" for event in result.events)
    assert result.data_result is None
    assert "sentinel-private-path" not in result.model_dump_json()
    destination = save_workflow(result, tmp_path)
    assert not (destination / "report.md").exists()


def test_actual_tool_exception_has_failed_event_and_no_downstream_model_call(monkeypatch):
    def fail_tool(*args):
        raise RuntimeError("sentinel-private-tool-error")

    monkeypatch.setattr("office_agents.agents.data.run_data_tools", fail_tool)
    result, calls = execute()
    assert result.status == "failed"
    assert [role_of(call) for call in calls] == ["manager", "planner", "data"]
    tool_events = [event for event in result.events if event.event_type == "tool_execution"]
    assert len(tool_events) == 1
    assert tool_events[0].status == "failed"
    assert "sentinel-private-tool-error" not in result.model_dump_json()


@pytest.mark.parametrize(
    ("user_text", "expected"),
    [
        (Q2, [{"start_date": "2026-04-01", "end_date": "2026-07-01"}]),
        (
            "生成研发部2026年第四季度工作报告",
            [{"start_date": "2026-10-01", "end_date": "2027-01-01"}],
        ),
        ("生成研发部第二季度工作报告", []),
        (
            "研发部2026-04-01到2026-07-01报告",
            [{"start_date": "2026-04-01", "end_date": "2026-07-01"}],
        ),
    ],
)
def test_manager_http_context_has_only_user_grounded_date_hints(user_text, expected):
    _, calls = execute(user_text)
    assert user_context(calls[0])["grounded_date_ranges"] == expected


def test_date_hints_do_not_silently_repair_a_wrong_model_answer():
    def mutate(payload, response):
        if role_of(payload) != "manager":
            return response

        def edit(content):
            content["requirements"]["end_date"] = "2026-06-30"

        return change_completion(response, edit)

    result, calls = execute(mutate=mutate)
    assert result.status == "failed"
    assert len(calls) == 1
    assert result.requirements is None
    assert result.nodes[0].output is None
    assert "Manager requirements invalid or ungrounded" in result.error
