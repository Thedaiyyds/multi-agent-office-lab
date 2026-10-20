"""Independent acceptance: ordinary materials through the normal workbench.

All application state is temporary; model transports are local scripted fixtures.
The public sample originals, developer configuration and running services are untouched.
"""

import json
import re
import time
from contextlib import contextmanager
from pathlib import Path
from threading import Event
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from office_agents.config import Settings
from office_agents.workbench.api import create_app

SAMPLES = Path(__file__).resolve().parents[1] / "data/demo"
TECHNICAL = (
    "生成2026年第二季度技术部工作汇报，包含项目进度、人员考勤、成果统计，"
    "格式为Markdown，导出为PDF。考勤仅说明已提供材料样本，不推断整个季度。"
)
ADMINISTRATION = "生成2026年第一季度行政部工作汇报，重点突出行政服务满意度，格式为Markdown。"
TERMINAL = {"completed", "needs_input", "failed", "review_failed", "cancelled", "interrupted"}


@contextmanager
def workbench(tmp_path, **execution_options):
    """Start the real application/worker with an explicit non-secret test config."""
    options = {
        "settings_factory": lambda: Settings(
            base_url="https://acceptance.invalid/v1",
            model="local-scripted-test",
            api_key="not-a-real-key",
            max_retries=0,
        ),
        **execution_options,
    }
    app = create_app(
        database_path=tmp_path / "acceptance.sqlite3",
        static_dir=False,
        execution_options=options,
    )
    with TestClient(app) as client:
        yield client, app


def upload(client, name, kind, raw, *, department, start, end, workspace="normal"):
    headers = {"X-Workspace": workspace}
    response = client.post(
        "/api/v1/materials/import",
        headers=headers,
        data={"kind": kind, "department": department, "start_date": start, "end_date": end},
        files={"file": (name, raw)},
    )
    assert response.status_code == 201, response.text
    staged = response.json()
    response = client.post(
        f"/api/v1/imports/{staged['id']}/confirm",
        headers=headers,
        json={
            "mapping": staged["suggested_mapping"],
            "department": department,
            "start_date": start,
            "end_date": end,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def ordinary_case(client, case="technical-q2", *, workspace="normal"):
    if case == "technical-q2":
        department, start, end = "技术部", "2026-04-01", "2026-07-01"
        files = [
            ("项目进度.csv", "projects"),
            ("人员考勤.csv", "attendance"),
            ("成果统计.csv", "achievements"),
            ("工作说明.txt", "notes"),
            ("季度工作记录.docx", "notes"),
        ]
    else:
        department, start, end = "行政部", "2026-01-01", "2026-04-01"
        files = [("满意度.csv", "satisfaction"), ("服务说明.txt", "notes")]
    return [
        upload(
            client,
            name,
            kind,
            (SAMPLES / case / name).read_bytes(),
            department=department,
            start=start,
            end=end,
            workspace=workspace,
        )
        for name, kind in files
    ]


def submit(client, materials, text=TECHNICAL, *, key=None, workspace="normal", **changes):
    return client.post(
        "/api/v1/runs",
        headers={"X-Workspace": workspace, "Idempotency-Key": key or str(uuid4())},
        json={
            "user_text": text,
            "material_ids": [item["id"] for item in materials],
            "mode": "offline_mock",
            **changes,
        },
    )


def finished(client, run_id, *, workspace="normal"):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/runs/{run_id}", headers={"X-Workspace": workspace})
        assert response.status_code == 200, response.text
        run = response.json()
        if run["status"] in TERMINAL:
            return run
        time.sleep(0.01)
    raise AssertionError(f"Local fixture run {run_id} did not reach a terminal state")


def completion(content):
    """A scripted provider envelope; no network request or private config exists."""
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {"role": "assistant", "content": json.dumps(content)},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
        },
    )


class ScriptedProvider:
    """Independent role responses with optional adversarial edits at the HTTP edge."""

    def __init__(self, mutate=None):
        self.calls = []
        self.mutate = mutate

    def __call__(self, request):
        body = json.loads(request.content)
        system = body["messages"][0]["content"]
        role = re.search(r"ROLE=(\w+)", system)[1]
        phase = re.search(r"PHASE=(\w+)", system)[1]
        context = json.loads(body["messages"][1]["content"])
        self.calls.append((role, phase, context))
        if phase == "requirements":
            administrative = "行政部" in context["user_text"]
            requirements = {
                "title": "行政服务工作汇报" if administrative else "技术部工作汇报",
                "department": "行政部" if administrative else "技术部",
                "start_date": "2026-01-01" if administrative else "2026-04-01",
                "end_date": "2026-04-01" if administrative else "2026-07-01",
                "focus": "整理所选材料，说明统计口径与局限",
                "sections": ["工作概况", "主要成果", "问题与风险", "后续计划"],
            }
            if context["saved_report"]:
                requirements = {key: context["saved_report"][key] for key in requirements}
            reply = {
                "status": "ready",
                "requirements": requirements,
                "tasks": ["内容规划", "数据整理", "报告撰写", "审核验收"],
                "missing_fields": [],
                "questions": [],
            }
        elif phase == "outline":
            requested = (
                ["satisfaction"]
                if context["requirements"]["department"] == "行政部"
                else ["projects", "attendance", "achievements"]
            )
            reply = {
                "sections": [
                    {"title": title, "purpose": "依据授权材料说明本节内容", "groups": requested}
                    for title in context["requirements"]["sections"]
                ],
                "groups": requested,
            }
        elif phase == "summary":
            reply = {"summary": "已按大纲整理，数值以确定性工具为准。", "limitations": []}
        elif phase == "draft":
            references = " ".join(
                f"[[fact:{fact['id']}]]" for fact in context["facts"] if fact["value"] is not None
            )
            reply = {
                "sections": [
                    {
                        "title": section["title"],
                        "text": "依据授权材料整理。"
                        + (references if index == 0 else "结论限于所提供样本，详见统计与来源。"),
                    }
                    for index, section in enumerate(context["outline"]["sections"])
                ],
                "suggestions": ["建议持续完善业务记录并复核来源。"],
            }
        elif phase == "review":
            # Deliberately approving: local safeguards must independently reject bad drafts.
            reply = {"passed": True, "issues": [], "revision_instructions": []}
        elif phase == "acceptance":
            reply = {"accepted": True, "reasons": ["已核对需求、审核与结果"]}
        else:
            raise AssertionError((role, phase))
        if self.mutate:
            edited = self.mutate(role, phase, context, reply)
            if isinstance(edited, httpx.Response):
                return edited
            if edited is not None:
                reply = edited
        return completion(reply)


def successful_submit(client, materials, **changes):
    response = submit(client, materials, **changes)
    assert response.status_code == 202, response.text
    return finished(client, response.json()["id"])


def metric_values(run):
    return {metric["id"]: metric["value"] for metric in run["statistics"]["metrics"]}


def test_normal_technical_case_has_real_role_dependencies_and_frozen_sources(tmp_path):
    original = {
        path: path.read_bytes() for path in (SAMPLES / "technical-q2").iterdir() if path.is_file()
    }
    with workbench(tmp_path) as (client, _):
        materials = ordinary_case(client)
        run = successful_submit(client, materials)
        assert run["status"] == "completed", run
        assert [node["role"] for node in run["nodes"]] == [
            "manager",
            "planner",
            "data",
            "writer",
            "checker",
            "manager",
        ]
        assert run["nodes"][-1]["inputs"]["phase"] == "acceptance"
        assert run["acceptance"]["accepted"] is True
        assert run["review"]["passed"] and run["review"]["program_passed"]
        values = metric_values(run)
        assert {
            key: values[key]
            for key in (
                "project_count",
                "completed_project_count",
                "completion_rate",
                "achievement_count",
                "sample_planned_hours",
                "sample_actual_hours",
                "sample_leave_hours",
                "sample_attendance_rate",
                "attendance_coverage",
                "attendance_rate",
            )
        } == {
            "project_count": 4,
            "completed_project_count": 2,
            "completion_rate": 0.5,
            "achievement_count": 3,
            "sample_planned_hours": 32,
            "sample_actual_hours": 28,
            "sample_leave_hours": 4,
            "sample_attendance_rate": 0.875,
            "attendance_coverage": None,
            "attendance_rate": None,
        }
        assert "87.50%" in run["draft_markdown"]
        assert "不等于部门整个期间" in run["draft_markdown"]
        assert "离线夹具" in run["draft_markdown"]
        assert run["usage"]["request_count"] == 0
        assert run["usage"]["mock_calls"] == 6
        assert run["usage"]["total_tokens"] is None
        by_id = {item["id"]: item for item in materials}
        for fact in run["facts"]:
            for ref in fact["source_refs"]:
                assert ref["sha256"] == by_id[ref["material_id"]]["sha256"]
        assert any(note["name"].endswith(".docx") for note in run["notes"])
        assert run["nodes"][2]["inputs"]["outline"] == run["outline"]
        writer_input = next(
            node["inputs"]["context"] for node in run["nodes"] if node["role"] == "writer"
        )
        assert {fact["id"] for fact in writer_input["facts"]} == {
            fact["id"] for fact in run["facts"]
        }
        assert run["nodes"][-1]["inputs"]["context"]["review"]["passed"] is True
        assert client.get("/api/v1/reports").json()["items"][0]["id"] == run["report_id"]
    assert all(path.read_bytes() == raw for path, raw in original.items())


def test_normal_administration_case_preserves_scale_and_avoids_previous_period_claim(tmp_path):
    with workbench(tmp_path) as (client, _):
        materials = ordinary_case(client, "administration-q1")
        run = successful_submit(client, materials, text=ADMINISTRATION)
        assert run["status"] == "completed", run
        assert run["outline"]["groups"] == ["satisfaction"]
        assert metric_values(run) == {"satisfaction_mean_0": 4, "satisfaction_count_0": 4}
        assert "1–5 量表" in run["draft_markdown"]
        assert run["requirements"]["start_date"] == "2026-01-01"
        assert run["requirements"]["end_date"] == "2026-04-01"


def test_planner_output_actually_limits_data_tools_even_with_other_materials_selected(tmp_path):
    def projects_only(role, phase, context, reply):
        if phase == "outline":
            reply["groups"] = ["projects"]
            for section in reply["sections"]:
                section["groups"] = ["projects"]
        return reply

    provider = ScriptedProvider(projects_only)
    with workbench(tmp_path, transport=httpx.MockTransport(provider)) as (client, _):
        run = successful_submit(client, ordinary_case(client), mode="live")
        assert run["status"] == "completed", run
        assert set(metric_values(run)) == {
            "project_count",
            "completed_project_count",
            "completion_rate",
            "completed_in_period",
        }
        assert [role for role, _, _ in provider.calls] == [
            "manager",
            "planner",
            "data",
            "writer",
            "checker",
            "manager",
        ]
        data_input = next(context for role, _, context in provider.calls if role == "data")
        assert data_input["outline"]["groups"] == ["projects"]
        planner_input = next(context for role, _, context in provider.calls if role == "planner")
        assert planner_input["manager"]["status"] == "ready"
        assert planner_input["manager"]["tasks"] == ["内容规划", "数据整理", "报告撰写", "审核验收"]
        assert run["usage"]["request_count"] == 6
        assert run["usage"]["total_tokens"] == 180


@pytest.mark.parametrize(
    "bad_text",
    [
        "本季度已完成99个项目。",
        "本季度已完成九十九个项目。",
        "参考[[fact:F999]]。",
        "参考[[note:N999]]。",
        "参考[[fact:F1]]。",
        "普通段落\n# 不允许的额外标题",
        "<script>执行</script>",
    ],
)
def test_program_rejects_bad_writer_even_when_model_checker_approves(tmp_path, bad_text):
    def corrupt(role, phase, context, reply):
        if phase == "draft":
            reply["sections"][0]["text"] = bad_text
        return reply

    provider = ScriptedProvider(corrupt)
    with workbench(tmp_path, transport=httpx.MockTransport(provider)) as (client, _):
        run = successful_submit(client, ordinary_case(client), mode="live", max_revisions=0)
        assert run["status"] == "review_failed", run
        assert run["review"]["model_passed"] is True
        assert run["review"]["program_passed"] is False
        assert run["acceptance"] is None
        assert not any(phase == "acceptance" for _, phase, _ in provider.calls)


def test_checker_feedback_drives_a_real_writer_revision_before_final_manager_acceptance(tmp_path):
    def initial_mistake(role, phase, context, reply):
        if phase == "draft" and context["revision"] == 0:
            reply["sections"][0]["text"] = "完成99项。"
        if phase == "draft" and context["revision"] == 1:
            assert context["previous_review"]["program_passed"] is False
            assert context["previous_review"]["revision_instructions"]
        return reply

    provider = ScriptedProvider(initial_mistake)
    with workbench(tmp_path, transport=httpx.MockTransport(provider)) as (client, _):
        run = successful_submit(client, ordinary_case(client), mode="live")
        assert run["status"] == "completed", run
        assert [revision["review"]["passed"] for revision in run["revision_history"]] == [
            False,
            True,
        ]
        assert run["acceptance"]["accepted"] is True
        assert sum(role == "writer" for role, _, _ in provider.calls) == 2
        assert "完成99项" not in run["draft_markdown"]
        assert "完成99项" in run["revision_history"][0]["markdown"]


def test_persistent_bad_draft_stops_after_two_revisions_without_final_acceptance(tmp_path):
    def never_correct(role, phase, context, reply):
        if phase == "draft":
            reply["sections"][0]["text"] = "完成99项。"
        return reply

    provider = ScriptedProvider(never_correct)
    with workbench(tmp_path, transport=httpx.MockTransport(provider)) as (client, _):
        run = successful_submit(client, ordinary_case(client), mode="live")
        assert run["status"] == "review_failed", run
        assert len(run["revision_history"]) == 3
        assert sum(role == "writer" for role, _, _ in provider.calls) == 3
        assert run["acceptance"] is None


def test_final_manager_can_reject_a_checker_approved_draft(tmp_path):
    def manager_rejects(role, phase, context, reply):
        if phase == "acceptance":
            return {"accepted": False, "reasons": ["需要补充业务解释"]}
        return reply

    provider = ScriptedProvider(manager_rejects)
    with workbench(tmp_path, transport=httpx.MockTransport(provider)) as (client, _):
        run = successful_submit(client, ordinary_case(client), mode="live")
        assert run["review"]["passed"] is True
        assert run["status"] == "review_failed"
        assert run["acceptance"] == {"accepted": False, "reasons": ["需要补充业务解释"]}


def test_missing_requirement_or_authorized_material_stops_with_specific_next_steps(tmp_path):
    with workbench(tmp_path) as (client, _):
        missing_year = successful_submit(client, [], text="生成技术部工作汇报")
        assert missing_year["status"] == "needs_input"
        assert missing_year["report_id"] is None
        assert missing_year["missing_fields"] and missing_year["questions"]
        assert client.get("/api/v1/reports").json()["items"] == []
        no_material = successful_submit(client, [])
        assert no_material["status"] == "needs_input"
        assert no_material["missing_fields"] == ["materials"]
        assert not any(node["role"] == "writer" for node in no_material["nodes"])


def test_space_isolation_and_idempotency_are_enforced_by_server(tmp_path):
    with workbench(tmp_path) as (client, _):
        materials = ordinary_case(client)
        key = str(uuid4())
        first = submit(client, materials, key=key)
        assert first.status_code == 202
        run = finished(client, first.json()["id"])
        repeated = submit(client, materials, key=key)
        assert repeated.status_code == 202
        assert repeated.json()["id"] == run["id"]
        assert submit(client, materials, key=key, text=ADMINISTRATION).status_code == 409
        assert len(client.get("/api/v1/runs").json()["items"]) == 1
        assert client.get("/api/v1/runs", headers={"X-Workspace": "demo"}).json()["items"] == []
        assert (
            client.get(f"/api/v1/runs/{run['id']}", headers={"X-Workspace": "demo"}).status_code
            == 404
        )
        assert (
            client.post(
                f"/api/v1/runs/{run['id']}/cancel", headers={"X-Workspace": "demo"}
            ).status_code
            == 404
        )
        assert submit(client, materials, workspace="demo").status_code == 404


@pytest.mark.parametrize(
    "limits,code,count",
    [
        ({"request_budget": 1}, "request_budget", 1),
        ({"output_budget": 100}, "output_budget", 0),
    ],
)
def test_budget_admission_is_persisted_before_provider_and_never_reset(
    tmp_path, limits, code, count
):
    provider = ScriptedProvider()
    with workbench(tmp_path, transport=httpx.MockTransport(provider)) as (client, _):
        run = successful_submit(client, ordinary_case(client), mode="live", **limits)
        assert run["status"] == "failed"
        assert run["error"]["code"] == code
        assert len(provider.calls) == count
        assert run["usage"]["request_count"] == count
        assert run["usage"]["reserved_output_tokens"] == 256 * count
        run_id = run["id"]
    with workbench(tmp_path, transport=httpx.MockTransport(provider)) as (client, _):
        restored = client.get(f"/api/v1/runs/{run_id}").json()
        assert restored == run
        assert len(provider.calls) == count


def test_cancel_inflight_and_queued_runs_cannot_become_completed_on_late_return(tmp_path):
    entered, release = Event(), Event()

    def block_manager(role, phase, context, reply):
        if phase == "requirements":
            entered.set()
            assert release.wait(5)
        return reply

    provider = ScriptedProvider(block_manager)
    with workbench(tmp_path, transport=httpx.MockTransport(provider)) as (client, _):
        materials = ordinary_case(client)
        response = submit(client, materials, mode="live")
        assert response.status_code == 202
        first_id = response.json()["id"]
        try:
            assert entered.wait(3)
            reserved = client.get(f"/api/v1/runs/{first_id}").json()
            assert reserved["usage"]["request_count"] == 1
            assert reserved["usage"]["reserved_output_tokens"] == 256
            second = submit(client, materials, mode="live")
            second_id = second.json()["id"]
            assert client.post(f"/api/v1/runs/{second_id}/cancel").json()["status"] == "cancelled"
            client.post(f"/api/v1/runs/{first_id}/cancel")
        finally:
            release.set()
        first = finished(client, first_id)
        assert first["status"] == "cancelled"
        assert first["report_id"] is None
        assert first["acceptance"] is None
        assert len(provider.calls) == 1
        assert finished(client, second_id)["status"] == "cancelled"


def test_second_server_without_execution_lease_does_not_interrupt_owner(tmp_path):
    entered, release = Event(), Event()

    def block_manager(role, phase, context, reply):
        if phase == "requirements":
            entered.set()
            assert release.wait(5)
        return reply

    provider = ScriptedProvider(block_manager)
    with workbench(tmp_path, transport=httpx.MockTransport(provider)) as (owner, _):
        materials = ordinary_case(owner)
        response = submit(owner, materials, mode="live")
        assert response.status_code == 202
        run_id = response.json()["id"]
        try:
            assert entered.wait(3)
            with workbench(tmp_path) as (second, _):
                assert second.get(f"/api/v1/runs/{run_id}").json()["status"] == "running"
                assert submit(second, materials).status_code == 503
            assert owner.get(f"/api/v1/runs/{run_id}").json()["status"] == "running"
        finally:
            release.set()
        assert finished(owner, run_id)["status"] == "completed"


def test_shutdown_marks_inflight_unknown_and_restart_does_not_reissue_billable_request(tmp_path):
    entered, release = Event(), Event()

    def block_manager(role, phase, context, reply):
        if phase == "requirements":
            entered.set()
            assert release.wait(5)
        return reply

    provider = ScriptedProvider(block_manager)
    try:
        with workbench(tmp_path, transport=httpx.MockTransport(provider)) as (client, first_app):
            response = submit(client, ordinary_case(client), mode="live")
            assert response.status_code == 202
            run_id = response.json()["id"]
            assert entered.wait(3)
            reserved = client.get(f"/api/v1/runs/{run_id}").json()
            assert reserved["usage"]["request_count"] == 1
            assert reserved["model_attempts"][0]["status"] == "reserved"
        # Closing does not wait for an uncertain supplier result or release its lease early.
        with workbench(tmp_path) as (second, _):
            interrupted = second.get(f"/api/v1/runs/{run_id}").json()
            assert interrupted["status"] == "interrupted"
            assert interrupted["usage"]["reserved_output_tokens"] == 256
            assert submit(second, []).status_code == 503
    finally:
        release.set()
    first_app.state.execution_service._worker.join(timeout=3)
    assert not first_app.state.execution_service._worker.is_alive()
    with workbench(tmp_path, transport=httpx.MockTransport(provider)) as (restarted, _):
        restored = restarted.get(f"/api/v1/runs/{run_id}").json()
        assert restored["status"] == "interrupted"
        assert restored["usage"]["request_count"] == 1
        assert restored["acceptance"] is None
        assert len(provider.calls) == 1


def test_provider_error_does_not_leak_body_credentials_or_fake_usage(tmp_path):
    secret = "PRIVATE_PROVIDER_BODY_should_never_be_stored"

    def denied(role, phase, context, reply):
        return httpx.Response(401, json={"error": secret})

    provider = ScriptedProvider(denied)
    with workbench(tmp_path, transport=httpx.MockTransport(provider)) as (client, _):
        run = successful_submit(client, ordinary_case(client), mode="live")
        assert run["status"] == "failed"
        assert run["error"]["code"] == "authentication"
        assert run["usage"]["request_count"] == 1
        assert run["usage"]["total_tokens"] is None
        assert secret not in json.dumps(run)
        assert "not-a-real-key" not in json.dumps(run)
        assert len(provider.calls) == 1


def test_normal_local_interface_can_supply_case_without_switching_workspace(tmp_path):
    with workbench(tmp_path) as (client, _):
        run = successful_submit(client, [], use_local_api=True)
        assert run["status"] == "completed", run
        assert metric_values(run)["project_count"] == 12
        assert metric_values(run)["person_days"] == 1560
        assert metric_values(run)["attendance_rate"] is None
        assert {source["kind"] for source in run["source_datasets"]} == {
            "projects",
            "attendance",
            "achievements",
        }
        assert all(
            source["material_id"] in run["material_ids"] for source in run["source_datasets"]
        )
        assert all(source["sha256"] for source in run["source_datasets"])
        assert (
            client.get("/api/v1/materials", headers={"X-Workspace": "demo"}).json()["items"] == []
        )


def test_missing_planner_requested_group_stops_before_writer_without_inventing_zero(tmp_path):
    with workbench(tmp_path) as (client, _):
        only_projects = [item for item in ordinary_case(client) if item["kind"] == "projects"]
        run = successful_submit(client, only_projects)
        assert run["status"] == "needs_input"
        assert metric_values(run)["achievement_count"] is None
        assert metric_values(run)["person_days"] is None
        assert run["draft_markdown"] is None
        assert not any(node["role"] == "writer" for node in run["nodes"])


def test_conflicting_materials_stop_data_without_model_or_writer_covering_up_error(tmp_path):
    with workbench(tmp_path) as (client, _):
        materials = ordinary_case(client)
        raw = (SAMPLES / "technical-q2/项目进度.csv").read_bytes()
        changed = raw.replace(b"in_progress,50,", b"in_progress,51,", 1)
        assert changed != raw
        other = upload(
            client,
            "另一来源.csv",
            "projects",
            changed,
            department="技术部",
            start="2026-04-01",
            end="2026-07-01",
        )
        run = successful_submit(client, [*materials, other])
        assert run["status"] == "failed"
        assert run["error"]["code"] == "invalid_data"
        assert all(value is None for value in metric_values(run).values())
        assert not any(node["role"] == "writer" for node in run["nodes"])


def test_editing_existing_report_during_inflight_manager_prevents_old_scope_completion(tmp_path):
    entered, release = Event(), Event()

    def block_manager(role, phase, context, reply):
        if phase == "requirements":
            entered.set()
            assert release.wait(5)
        return reply

    provider = ScriptedProvider(block_manager)
    with workbench(tmp_path, transport=httpx.MockTransport(provider)) as (client, _):
        payload = {
            "title": "技术部季度汇报",
            "department": "技术部",
            "start_date": "2026-04-01",
            "end_date": "2026-07-01",
            "focus": "项目与成果",
            "sections": ["工作概况", "主要成果", "问题与风险", "后续计划"],
        }
        report = client.post("/api/v1/reports", json=payload).json()
        materials = ordinary_case(client)
        assert (
            submit(client, materials, report_id=report["id"], expected_version=2).status_code == 409
        )
        response = submit(
            client, materials, mode="live", report_id=report["id"], expected_version=1
        )
        assert response.status_code == 202
        run_id = response.json()["id"]
        try:
            assert entered.wait(3)
            changed = client.patch(
                f"/api/v1/reports/{report['id']}/draft",
                json={**payload, "focus": "新重点", "expected_version": 1},
            )
            assert changed.status_code == 200, changed.text
        finally:
            release.set()
        run = finished(client, run_id)
        assert run["status"] == "failed"
        assert run["error"]["code"] == "stale_report"
        assert run["report_version"] == 1
        assert run["acceptance"] is None
        assert len(provider.calls) == 1


def test_cancelling_during_final_acceptance_cannot_publish_late_success(tmp_path):
    entered, release = Event(), Event()

    def block_acceptance(role, phase, context, reply):
        if phase == "acceptance":
            entered.set()
            assert release.wait(5)
        return reply

    provider = ScriptedProvider(block_acceptance)
    with workbench(tmp_path, transport=httpx.MockTransport(provider)) as (client, _):
        response = submit(client, ordinary_case(client), mode="live")
        assert response.status_code == 202
        run_id = response.json()["id"]
        try:
            assert entered.wait(3)
            before = client.get(f"/api/v1/runs/{run_id}").json()
            assert before["review"]["passed"] is True
            assert before["acceptance"] is None
            client.post(f"/api/v1/runs/{run_id}/cancel")
        finally:
            release.set()
        run = finished(client, run_id)
        assert run["status"] == "cancelled"
        assert run["draft_markdown"]
        assert run["acceptance"] is None
        assert run["usage"]["request_count"] == 6
        assert len(provider.calls) == 6


def test_manager_inclusive_quarter_end_candidate_is_preserved_but_rejected(tmp_path):
    def wrong_exclusive_end(role, phase, context, reply):
        if phase == "requirements":
            reply["requirements"]["end_date"] = "2026-06-30"
        return reply

    provider = ScriptedProvider(wrong_exclusive_end)
    with workbench(tmp_path, transport=httpx.MockTransport(provider)) as (client, _):
        run = successful_submit(client, ordinary_case(client), mode="live")
        assert run["status"] == "failed"
        assert run["error"]["code"] == "ungrounded_period"
        assert run["report_id"] is None
        assert run["requirements"] is None
        assert len(provider.calls) == 1
        assert run["usage"]["request_count"] == 1
        assert run["usage"]["reserved_output_tokens"] == 256
        manager = run["nodes"][0]
        assert manager["status"] == "failed"
        assert manager["candidate_status"] == "pending_business_validation"
        assert manager["candidate_output"]["requirements"]["end_date"] == "2026-06-30"
        assert isinstance(manager["candidate_output"], dict)
        assert manager["inputs"]["context"]["grounded_periods"] == [
            {"start_date": "2026-04-01", "end_date": "2026-07-01"}
        ]
        assert client.get("/api/v1/reports").json()["items"] == []


@pytest.mark.parametrize(
    "case,text,start,end",
    [
        ("technical-q2", TECHNICAL, "2026-04-01", "2026-07-01"),
        ("administration-q1", ADMINISTRATION, "2026-01-01", "2026-04-01"),
    ],
)
def test_manager_can_copy_grounded_half_open_period_without_relaxing_business_check(
    tmp_path, case, text, start, end
):
    def use_grounded_hint(role, phase, context, reply):
        if phase == "requirements":
            assert context["grounded_periods"] == [{"start_date": start, "end_date": end}]
            reply["requirements"].update(context["grounded_periods"][0])
        return reply

    provider = ScriptedProvider(use_grounded_hint)
    with workbench(tmp_path, transport=httpx.MockTransport(provider)) as (client, _):
        run = successful_submit(client, ordinary_case(client, case), text=text, mode="live")
        assert run["status"] == "completed", run
        assert run["requirements"]["start_date"] == start
        assert run["requirements"]["end_date"] == end
        assert run["nodes"][0]["candidate_status"] == "node_completed"
        assert run["nodes"][0]["candidate_output"] == run["nodes"][0]["output"]
        assert run["acceptance"]["accepted"] is True


def test_manager_unmentioned_department_has_distinct_safe_business_failure(tmp_path):
    def change_department(role, phase, context, reply):
        if phase == "requirements":
            reply["requirements"]["department"] = "财务部"
        return reply

    provider = ScriptedProvider(change_department)
    with workbench(tmp_path, transport=httpx.MockTransport(provider)) as (client, _):
        run = successful_submit(client, ordinary_case(client), mode="live")
        assert run["status"] == "failed"
        assert run["error"]["code"] == "ungrounded_department"
        assert run["nodes"][0]["candidate_output"]["requirements"]["department"] == "财务部"
        assert run["report_id"] is None
        assert len(provider.calls) == 1
