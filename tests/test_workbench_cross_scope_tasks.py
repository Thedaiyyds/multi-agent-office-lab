"""Cross-scope planning and task housekeeping retain real files and audit evidence."""

import time

import httpx
import pytest
from test_workbench_execution_acceptance import (
    ScriptedProvider,
    finished,
    ordinary_case,
    submit,
    upload,
    workbench,
)
from test_workbench_planning import approve, confirmation, planned


def test_mixed_files_without_prompt_offer_compilation_and_separate_directions(tmp_path):
    with workbench(tmp_path) as (client, app):
        tech = ordinary_case(client)
        admin = ordinary_case(client, "administration-q1")
        run = planned(client, app, tech + admin)
        assert run["status"] == "awaiting_confirmation", run
        assert run["default_plan_option"] == "all"
        assert len(run["plan_options"]) == 3
        assert run["requirements"]["department"] == "多部门"
        assert set(run["outline"]["groups"]) == {
            "projects",
            "attendance",
            "achievements",
            "satisfaction",
        }
        assert run["statistics"] is None and run["report_id"] is None
        assert approve(client, run).status_code == 202
        assert app.state.execution_service.wait_for_idle(10)
        final = client.get("/api/v1/runs/" + run["id"]).json()
        assert final["status"] == "completed", final
        assert len(final["nodes"]) == 6 and final["usage"]["mock_calls"] == 6
        assert len(final["statistics"]["data_scopes"]) == 2
        tech_ids = {item["id"] for item in tech}
        admin_ids = {item["id"] for item in admin}
        for fact in final["facts"]:
            expected = tech_ids if fact["scope"]["department"] == "技术部" else admin_ids
            assert {ref["material_id"] for ref in fact["source_refs"]} <= expected
            assert fact["scope"]["department"] in fact["label"]
        values = {fact["metric_id"]: fact["value"] for fact in final["facts"]}
        assert values["scope1_project_count"] == 4
        assert values["scope2_satisfaction_mean_0"] == 4
        assert "project_count" not in values
        assert {note["scope"]["department"] for note in final["notes"]} == {"技术部", "行政部"}
        assert "## 汇编范围" in final["draft_markdown"]
        assert "2026-01-01" in final["draft_markdown"] and "2026-07-01" in final["draft_markdown"]
        base = f"/api/v1/reports/{final['report_id']}/revisions"
        for _ in range(100):
            versions = client.get(base).json()["items"]
            if versions and all(item["state"] == "ready" for item in versions[0]["artifacts"]):
                break
            time.sleep(0.05)
        for fmt in ["md", "pdf"]:
            response = client.get(f"{base}/{versions[0]['id']}/exports/{fmt}")
            assert response.status_code == 200 and response.content
        retried = submit(
            client,
            tech + admin,
            text=run["user_text"],
            report_id=final["report_id"],
            expected_version=1,
        )
        assert retried.status_code == 202
        assert app.state.execution_service.wait_for_idle(10)
        rerun = client.get("/api/v1/runs/" + retried.json()["id"]).json()
        assert rerun["status"] == "completed", rerun
        assert rerun["data_scopes"] == final["data_scopes"]
        assert {fact["metric_id"]: fact["value"] for fact in rerun["facts"]} == values
        tasks = client.get("/api/v1/tasks").json()["items"]
        assert len(tasks) == 1 and tasks[0]["run_count"] == 2


def test_user_can_choose_one_direction_without_unrelated_metrics(tmp_path):
    with workbench(tmp_path) as (client, app):
        run = planned(
            client, app, ordinary_case(client) + ordinary_case(client, "administration-q1")
        )
        option = next(item for item in run["plan_options"] if item["department"] == "行政部")
        payload = confirmation(run)
        payload["option_id"] = option["id"]
        payload["requirements"].update(
            {key: option[key] for key in ["title", "department", "start_date", "end_date"]}
        )
        payload["outline"]["groups"] = ["satisfaction"]
        for section in payload["outline"]["sections"]:
            section["groups"] = ["satisfaction"]
        assert approve(client, run, payload).status_code == 202
        assert app.state.execution_service.wait_for_idle(10)
        final = client.get("/api/v1/runs/" + run["id"]).json()
        assert final["status"] == "completed", final
        assert {fact["metric_id"] for fact in final["facts"]} == {
            "satisfaction_mean_0",
            "satisfaction_count_0",
        }
        assert all(note["name"] != "工作说明.txt" for note in final["notes"])


def test_scripted_agents_receive_all_scopes_and_continue_without_replanning(tmp_path):
    def adapt(role, phase, context, reply):
        if phase == "requirements":
            reply["requirements"].update(context["suggested_scope"])
            reply["requirements"]["title"] = context["suggested_title"]
        if phase == "outline":
            reply["groups"] = context["available_groups"]
            for section in reply["sections"]:
                section["groups"] = context["available_groups"]
        return reply

    provider = ScriptedProvider(adapt)
    with workbench(tmp_path, transport=httpx.MockTransport(provider)) as (client, app):
        run = planned(
            client,
            app,
            ordinary_case(client) + ordinary_case(client, "administration-q1"),
            mode="live",
        )
        assert run["status"] == "awaiting_confirmation", run
        assert len(provider.calls[0][2]["material_profile"]["scopes"]) == 2
        assert len(provider.calls) == 2
        assert approve(client, run).status_code == 202
        assert app.state.execution_service.wait_for_idle(10)
        result = client.get("/api/v1/runs/" + run["id"]).json()
        assert result["status"] == "completed", result
        assert len(provider.calls) == 6


def test_tasks_group_run_history_and_hide_restore_without_deleting_reports(tmp_path):
    with workbench(tmp_path) as (client, app):
        materials = ordinary_case(client)
        run = finished(client, submit(client, materials).json()["id"])
        report_id = run["report_id"]
        second = submit(client, materials, report_id=report_id, expected_version=1)
        assert second.status_code == 202
        assert app.state.execution_service.wait_for_idle(10)
        result = client.get("/api/v1/tasks").json()
        assert len(result["items"]) == 1 and not result["attempts"]
        task = result["items"][0]
        assert (
            task["run_count"] == 2
            and task["report_id"] == report_id
            and task["status"] == "completed"
        )
        summary = client.get(
            "/api/v1/runs", params={"summary": "true", "report_id": report_id}
        ).json()
        assert len(summary["items"]) == 2
        assert "statistics" not in summary["items"][0] and "facts" not in summary["items"][0]
        response = client.post(
            "/api/v1/tasks/visibility", json={"ids": [task["id"]], "hidden": True}
        )
        assert response.status_code == 200
        assert client.get("/api/v1/tasks").json()["items"][0]["hidden"]
        assert len(client.get("/api/v1/reports").json()["items"]) == 1
        assert len(client.get("/api/v1/runs").json()["items"]) == 2
        assert (
            client.post(
                "/api/v1/tasks/visibility",
                json={"ids": [task["id"]], "hidden": True},
                headers={"X-Workspace": "demo"},
            ).status_code
            == 404
        )
        assert (
            client.post(
                "/api/v1/tasks/visibility", json={"ids": [task["id"]], "hidden": False}
            ).status_code
            == 200
        )
        assert not client.get("/api/v1/tasks").json()["items"][0]["hidden"]
        client.post("/api/v1/tasks/visibility", json={"ids": [task["id"]], "hidden": True})
        response = submit(client, materials, report_id=report_id, expected_version=1)
        assert app.state.execution_service.wait_for_idle(10)
        assert not client.get("/api/v1/tasks").json()["items"][0]["hidden"]


def test_pending_plan_is_one_task_then_moves_into_report_and_failed_attempts_are_collapsed(
    tmp_path,
):
    with workbench(tmp_path) as (client, app):
        materials = ordinary_case(client)
        for _ in range(2):
            submit(client, [], text="帮我写汇报")
            assert app.state.execution_service.wait_for_idle(10)
        listing = client.get("/api/v1/tasks").json()
        assert not listing["items"] and len(listing["attempts"]) == 1
        assert listing["attempts"][0]["run_count"] == 2
        run = planned(client, app, materials)
        listing = client.get("/api/v1/tasks").json()
        assert len(listing["items"]) == 1
        task = listing["items"][0]
        assert task["status"] == "awaiting_confirmation" and task["report_id"] is None
        assert (
            client.post(
                "/api/v1/tasks/visibility", json={"ids": [task["id"]], "hidden": True}
            ).status_code
            == 409
        )
        assert approve(client, run).status_code == 202
        assert app.state.execution_service.wait_for_idle(10)
        listing = client.get("/api/v1/tasks").json()
        assert len(listing["items"]) == 1 and listing["items"][0]["report_id"]
        assert listing["items"][0]["status"] == "completed"
        assert client.get("/api/v1/tasks", headers={"X-Workspace": "demo"}).json() == {
            "items": [],
            "attempts": [],
        }


@pytest.mark.parametrize("quarterly", [False, True])
def test_same_department_cross_quarter_file_supports_explicit_wide_period(tmp_path, quarterly):
    with workbench(tmp_path) as (client, app):
        material = upload(
            client,
            "半年成果.csv",
            "achievements",
            "achievement_id,department,date,category,name,project_id\n"
            "A1,技术部,2026-02-01,交付,第一季度交付,P1\n"
            "A2,技术部,2026-05-01,交付,第二季度交付,P2\n"
            "A3,技术部,2026-06-01,交付,第二季度改进,P3\n".encode(),
            department="技术部",
            start="2026-01-01",
            end="2026-07-01",
        )
        response = submit(
            client,
            [material],
            text="规划技术部2026-01-01至2026-07-01的工作汇编"
            + ("，按季度统计" if quarterly else ""),
            planning_only=True,
        )
        assert app.state.execution_service.wait_for_idle(10)
        run = client.get("/api/v1/runs/" + response.json()["id"]).json()
        assert run["status"] == "awaiting_confirmation", run
        assert run["default_plan_option"] == "scope-0"
        assert len(run["plan_options"][0]["scopes"]) == 1
        assert len(run["outline"].get("periods", [])) == (2 if quarterly else 0)
        assert approve(client, run).status_code == 202
        assert app.state.execution_service.wait_for_idle(10)
        final = client.get("/api/v1/runs/" + run["id"]).json()
        assert final["status"] == "completed", final
        counts = {fact["metric_id"]: fact["value"] for fact in final["facts"]}
        if quarterly:
            assert counts["scope1_achievement_count"] == 1
            assert counts["scope2_achievement_count"] == 2
        else:
            assert counts["achievement_count"] == 3
        assert len(final["statistics"]["data_scopes"]) == (2 if quarterly else 1)


def test_equivalent_quarter_and_dates_do_not_duplicate_a_scope(tmp_path):
    with workbench(tmp_path) as (client, app):
        response = submit(
            client,
            ordinary_case(client),
            text="技术部2026年第二季度，2026-04-01至2026-07-01汇报",
            planning_only=True,
        )
        assert app.state.execution_service.wait_for_idle(10)
        run = client.get("/api/v1/runs/" + response.json()["id"]).json()
        assert run["status"] == "awaiting_confirmation", run
        assert run["default_plan_option"] == "scope-0"
        assert len(run["plan_options"]) == 1
