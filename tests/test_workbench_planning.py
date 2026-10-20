"""Two-stage planning uses real local files and explicitly offline/scripted models."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path

import httpx
import pytest
from test_workbench_execution_acceptance import (
    ScriptedProvider,
    ordinary_case,
    submit,
    upload,
    workbench,
)


def planned(client, app, materials, **options):
    response = submit(client, materials, text="根据所选材料规划汇报", planning_only=True, **options)
    assert response.status_code == 202, response.text
    assert app.state.execution_service.wait_for_idle(10)
    return client.get("/api/v1/runs/" + response.json()["id"]).json()


def confirmation(run):
    return dict(
        plan_hash=run["plan_hash"],
        requirements=deepcopy(run["requirements"]),
        outline=deepcopy(run["outline"]),
    )


def approve(client, run, payload=None, key="confirm", workspace="normal"):
    return client.post(
        f"/api/v1/runs/{run['id']}/confirm-plan",
        json=payload or confirmation(run),
        headers={"Idempotency-Key": key, "X-Workspace": workspace},
    )


def test_plan_pauses_without_report_or_data_then_uses_user_edits_and_same_file_sources(tmp_path):
    with workbench(tmp_path) as (client, app):
        materials = ordinary_case(client)
        run = planned(client, app, materials)
        assert run["status"] == "awaiting_confirmation", run
        assert (
            run["report_id"] is None and run["statistics"] is None and run["draft_markdown"] is None
        )
        assert [node["role"] for node in run["nodes"]] == ["manager", "planner"]
        assert run["usage"]["mock_calls"] == 2 and run["usage"]["request_count"] == 0
        assert client.get("/api/v1/reports").json()["items"] == []
        assert run["plan_evidence"]["sections"][0]["material_ids"]
        assert "2026年第二季度" in run["requirements"]["title"]
        payload = confirmation(run)
        payload["requirements"]["title"] = "技术部季度交付复盘"
        payload["requirements"]["focus"] = "关注交付问题"
        payload["outline"]["sections"] = payload["outline"]["sections"][:2]
        payload["outline"]["sections"][0]["title"] = "交付概况"
        payload["requirements"]["sections"] = [
            section["title"] for section in payload["outline"]["sections"]
        ]
        result = approve(client, run, payload)
        assert result.status_code == 202, result.text
        assert app.state.execution_service.wait_for_idle(10)
        final = client.get("/api/v1/runs/" + run["id"]).json()
        assert final["status"] == "completed", final
        assert [node["role"] for node in final["nodes"]] == [
            "manager",
            "planner",
            "data",
            "writer",
            "checker",
            "manager",
        ]
        assert final["usage"]["mock_calls"] == 6
        assert final["requirements"] == payload["requirements"]
        assert final["outline"] == payload["outline"]
        assert final["nodes"][3]["inputs"]["context"]["outline"] == payload["outline"]
        assert "技术部季度交付复盘" in final["draft_markdown"]
        assert set(final["statistics"]["material_ids"]) == {item["id"] for item in materials}
        assert approve(client, run, payload).json()["id"] == run["id"]
        assert len(client.get("/api/v1/reports").json()["items"]) == 1
        assert approve(client, run, payload, key="different").status_code == 409


def test_confirm_is_atomic_workspace_scoped_and_bounded_by_files(tmp_path):
    with workbench(tmp_path) as (client, app):
        run = planned(client, app, ordinary_case(client))
        assert approve(client, run, workspace="demo").status_code == 404
        wrong = confirmation(run)
        wrong["plan_hash"] = "0" * 64
        assert approve(client, run, wrong).status_code == 409
        wrong = confirmation(run)
        wrong["requirements"]["department"] = "财务部"
        assert approve(client, run, wrong).status_code == 422
        payload = confirmation(run)
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(lambda _: approve(client, run, payload), range(2)))
        assert [result.status_code for result in results] == [202, 202]
        assert app.state.execution_service.wait_for_idle(10)
        assert len(client.get("/api/v1/reports").json()["items"]) == 1
        assert len(client.get("/api/v1/runs").json()["items"]) == 1


def test_mixed_materials_need_scope_and_cancelled_plan_never_generates(tmp_path):
    with workbench(tmp_path) as (client, app):
        technical = ordinary_case(client)
        administrative = ordinary_case(client, "administration-q1")
        ambiguous = planned(client, app, technical + administrative)
        assert ambiguous["status"] == "needs_input"
        assert ambiguous["usage"]["mock_calls"] == 0
        run = planned(client, app, technical)
        assert client.post(f"/api/v1/runs/{run['id']}/cancel").json()["status"] == "cancelled"
        assert approve(client, run).status_code == 409
        assert client.get("/api/v1/reports").json()["items"] == []


@pytest.mark.parametrize("damage", ["changed", "missing"])
def test_changed_or_missing_file_cannot_be_confirmed_using_cached_plan(tmp_path, damage):
    with workbench(tmp_path) as (client, app):
        run = planned(client, app, ordinary_case(client))
        service = app.state.execution_service.material_service
        path = service.original_path(service.get(run["material_ids"][0], "normal"))
        if damage == "changed":
            path.write_bytes(b"changed")
        else:
            path.unlink()
        assert approve(client, run).status_code in {404, 409}
        assert client.get("/api/v1/runs/" + run["id"]).json()["status"] == "awaiting_confirmation"
        assert client.get("/api/v1/reports").json()["items"] == []


def test_paused_plan_survives_restart_and_plain_text_plan_has_no_invented_metrics(tmp_path):
    with workbench(tmp_path) as (client, app):
        notes = [item for item in ordinary_case(client) if item["kind"] == "notes"]
        run = planned(client, app, notes)
        assert run["status"] == "awaiting_confirmation", run
        assert run["outline"]["groups"] == []
    with workbench(tmp_path) as (client, app):
        restored = client.get("/api/v1/runs/" + run["id"]).json()
        assert restored["status"] == "awaiting_confirmation"
        assert approve(client, restored).status_code == 202
        assert app.state.execution_service.wait_for_idle(10)
        result = client.get("/api/v1/runs/" + run["id"]).json()
        assert result["status"] == "completed", result
        assert result["facts"] == [] and result["notes"]
        assert len(result["nodes"]) == 6


def test_scripted_model_planning_costs_two_calls_then_four_and_keeps_total_usage(tmp_path):
    provider = ScriptedProvider()
    with workbench(tmp_path, transport=httpx.MockTransport(provider)) as (client, app):
        run = planned(client, app, ordinary_case(client), mode="live")
        assert run["status"] == "awaiting_confirmation", run
        assert len(provider.calls) == run["usage"]["request_count"] == 2
        assert [phase for _, phase, _ in provider.calls] == ["requirements", "outline"]
        assert approve(client, run).status_code == 202
        assert app.state.execution_service.wait_for_idle(10)
        result = client.get("/api/v1/runs/" + run["id"]).json()
        assert result["status"] == "completed", result
        assert len(provider.calls) == result["usage"]["request_count"] == 6
        assert [role for role, _, _ in provider.calls] == [
            "manager",
            "planner",
            "data",
            "writer",
            "checker",
            "manager",
        ]
        assert result["usage"]["total_tokens"] == sum(
            attempt["usage"]["total_tokens"] for attempt in result["model_attempts"]
        )


def test_approved_plan_exports_markdown_and_pdf(tmp_path):
    with workbench(tmp_path) as (client, app):
        run = planned(client, app, ordinary_case(client, "administration-q1"))
        assert approve(client, run).status_code == 202
        assert app.state.execution_service.wait_for_idle(10)
        final = client.get("/api/v1/runs/" + run["id"]).json()
        report = final["report_id"]
        # The delivery callback follows terminal persistence; wait only for local artifacts.
        import time

        for _ in range(100):
            revisions = client.get(f"/api/v1/reports/{report}/revisions").json()["items"]
            if revisions and all(item["state"] == "ready" for item in revisions[0]["artifacts"]):
                break
            time.sleep(0.05)
        revision = revisions[0]["id"]
        for fmt in ("md", "pdf"):
            response = client.get(f"/api/v1/reports/{report}/revisions/{revision}/exports/{fmt}")
            assert response.status_code == 200, response.text
            assert response.content


def test_explicit_scope_filters_other_department_groups_and_outside_period_is_not_guessed(tmp_path):
    with workbench(tmp_path) as (client, app):
        materials = ordinary_case(client) + ordinary_case(client, "administration-q1")
        response = submit(
            client, materials, text="重点规划技术部2026年第二季度汇报", planning_only=True
        )
        assert app.state.execution_service.wait_for_idle(10)
        run = client.get("/api/v1/runs/" + response.json()["id"]).json()
        assert run["status"] == "awaiting_confirmation", run
        assert set(run["outline"]["groups"]) == {"projects", "attendance", "achievements"}
        response = submit(
            client, materials, text="规划技术部2025年第二季度汇报", planning_only=True
        )
        assert app.state.execution_service.wait_for_idle(10)
        run = client.get("/api/v1/runs/" + response.json()["id"]).json()
        assert run["status"] == "needs_input" and run["requirements"] is None


def test_planning_and_generation_share_budget_instead_of_resetting_it(tmp_path):
    provider = ScriptedProvider()
    with workbench(tmp_path, transport=httpx.MockTransport(provider)) as (client, app):
        run = planned(client, app, ordinary_case(client), mode="live", request_budget=2)
        assert run["status"] == "awaiting_confirmation"
        assert approve(client, run).status_code == 202
        assert app.state.execution_service.wait_for_idle(10)
        result = client.get("/api/v1/runs/" + run["id"]).json()
        assert result["error"]["code"] == "request_budget"
        assert result["usage"]["request_count"] == len(provider.calls) == 2
        assert not any(role == "writer" for role, _, _ in provider.calls)


def test_large_files_profile_actual_record_counts_without_creating_a_report(tmp_path):
    root = Path(__file__).resolve().parents[1] / "data/office-cases/technical-q2"
    with workbench(tmp_path) as (client, app):
        materials = [
            upload(
                client,
                name,
                kind,
                (root / name).read_bytes(),
                department="技术部",
                start="2026-04-01",
                end="2026-07-01",
            )
            for name, kind in [
                ("项目进度.csv", "projects"),
                ("人员考勤.csv", "attendance"),
                ("成果统计.csv", "achievements"),
                ("工作说明.txt", "notes"),
            ]
        ]
        run = planned(client, app, materials)
        assert run["status"] == "awaiting_confirmation", run
        assert {file["name"]: file["row_count"] for file in run["material_profile"]["files"]} == {
            "项目进度.csv": 36,
            "人员考勤.csv": 1560,
            "成果统计.csv": 42,
            "工作说明.txt": 18,
        }
        assert run["statistics"] is None and not run["facts"] and run["report_id"] is None
