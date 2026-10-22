"""Five-role runs use local transports and temporary databases, never paid models."""

import json
import re
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from office_agents.config import ConfigurationError, Settings
from office_agents.workbench.demo import load_local_dataset
from office_agents.workbench.execution import (
    TERMINAL,
    ExecutionService,
    RunInput,
    _periods,
    create_execution_router,
)
from office_agents.workbench.materials import MaterialService, create_material_router

ROOT = Path(__file__).resolve().parents[1]
TECH_TEXT = "生成2026年第二季度技术部工作汇报，包含项目进度、人员考勤、成果统计。"
ADMIN_TEXT = "生成2026年第一季度行政部工作汇报，重点突出服务满意度。"


class Supplier:
    def __init__(self, *, bad_writer=0, bad_scope=False, malformed=None, blocked=None):
        self.calls = []
        self.bad_writer = bad_writer
        self.writer_count = 0
        self.bad_scope = bad_scope
        self.malformed = malformed
        self.blocked = blocked
        self.entered = threading.Event()
        self.release = threading.Event()

    def __call__(self, request):
        payload = json.loads(request.content)
        role = re.search(r"ROLE=(\w+)", payload["messages"][0]["content"])[1]
        phase = re.search(r"PHASE=(\w+)", payload["messages"][0]["content"])[1]
        context = json.loads(payload["messages"][1]["content"])
        self.calls.append((role, phase, payload))
        if self.blocked == phase:
            self.entered.set()
            assert self.release.wait(5), "test must release the bounded model request"
        if role == "manager" and phase == "requirements":
            saved = context["saved_report"]
            requirements = (
                {
                    key: saved[key]
                    for key in (
                        "title",
                        "department",
                        "start_date",
                        "end_date",
                        "focus",
                        "sections",
                    )
                }
                if saved
                else dict(
                    title="技术部工作汇报",
                    department="行政部" if self.bad_scope else "技术部",
                    start_date="2026-04-01",
                    end_date="2026-07-01",
                    focus="",
                    sections=["概况", "成果", "风险", "计划"],
                )
            )
            result = dict(
                status="ready",
                requirements=requirements,
                tasks=["拆解", "规划", "整理", "撰写", "校验"],
                missing_fields=[],
                questions=[],
            )
        elif role == "planner":
            result = dict(
                groups=["projects", "attendance", "achievements"],
                sections=[
                    dict(
                        title=title,
                        purpose="分析授权数据",
                        groups=["projects", "attendance", "achievements"],
                    )
                    for title in context["requirements"]["sections"]
                ],
            )
        elif role == "data":
            result = dict(summary="已整理授权数据。", limitations=[])
        elif role == "writer":
            self.writer_count += 1
            text = (
                "项目数量为999个。"
                if self.writer_count <= self.bad_writer
                else "依据授权事实 [[fact:F001]] 整理本期情况。"
            )
            result = dict(
                sections=[
                    dict(title=section["title"], text=text)
                    for section in context["outline"]["sections"]
                ],
                suggestions=["建议继续核对材料并完善后续安排。"],
            )
        elif role == "checker":
            # Intentionally permissive to prove deterministic validation wins.
            result = dict(passed=True, issues=[], revision_instructions=[])
        else:
            result = dict(accepted=True, reasons=["完成范围与审核校验"])
        content = json.dumps(result, ensure_ascii=False)
        if self.malformed == phase:
            content = '{"status":"ready","status":"needs_input"}'
        return httpx.Response(
            200,
            json=dict(
                choices=[
                    dict(message=dict(role="assistant", content=content), finish_reason="stop")
                ],
                usage=dict(
                    prompt_tokens=10,
                    completion_tokens=5,
                    total_tokens=15,
                    provider_secret="do not persist",
                ),
            ),
        )


@pytest.fixture
def build_app(tmp_path):
    database = tmp_path / "execution.sqlite3"

    @contextmanager
    def connection():
        db = sqlite3.connect(database, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    with connection() as db:
        db.execute("""CREATE TABLE reports(
            id TEXT PRIMARY KEY,workspace TEXT,title TEXT,department TEXT,
            start_date TEXT,end_date TEXT,focus TEXT,sections TEXT,version INTEGER,
            status TEXT,created_at TEXT,updated_at TEXT)""")
    material_service = MaterialService(connection, tmp_path / "materials")

    def factory(supplier=None, settings_factory=None):
        app = FastAPI()
        material_router = create_material_router(
            connection, material_service.root, ROOT / "data/demo"
        )
        app.include_router(material_router)
        router = create_execution_router(
            connection,
            material_service,
            settings_factory=settings_factory
            or (
                lambda: Settings(
                    base_url="https://test.invalid/v1",
                    model="test",
                    api_key="test-only",
                    max_retries=5,
                )
            ),
            transport=httpx.MockTransport(supplier) if supplier else None,
            local_provider=lambda kind: load_local_dataset(ROOT / "data/demo", kind),
        )
        app.include_router(router)
        app.state.execution_service = router.execution_service
        return app

    return factory, connection, material_service


def submit(client, *, text=TECH_TEXT, mode="offline_mock", key="test", **options):
    return client.post(
        "/api/v1/runs",
        headers={"Idempotency-Key": key},
        json=dict(user_text=text, mode=mode, use_local_api=True, **options),
    )


def finished(client, service, response):
    assert response.status_code == 202, response.text
    assert service.wait_for_idle(5), client.get("/api/v1/runs/" + response.json()["id"]).text
    return client.get("/api/v1/runs/" + response.json()["id"]).json()


@pytest.mark.parametrize(
    "text,expected",
    [
        (
            TECH_TEXT,
            {
                "project_count": 4,
                "completed_project_count": 2,
                "achievement_count": 3,
                "sample_planned_hours": 32,
                "sample_actual_hours": 28,
                "sample_leave_hours": 4,
            },
        ),
        (ADMIN_TEXT, {"satisfaction_mean_0": 4, "satisfaction_count_0": 4}),
    ],
)
def test_normal_workspace_offline_graph_uses_real_tools_and_all_five_roles(
    build_app, text, expected
):
    factory, connection, _ = build_app
    app = factory()
    with TestClient(app) as client:
        run = finished(client, app.state.execution_service, submit(client, text=text))
        assert run["status"] == "completed", run
        assert [node["role"] for node in run["nodes"]] == [
            "manager",
            "planner",
            "data",
            "writer",
            "checker",
            "manager",
        ]
        assert all(node["status"] == "completed" for node in run["nodes"])
        assert run["nodes"][-1]["inputs"]["phase"] == "acceptance"
        assert run["acceptance"]["accepted"]
        assert run["report_version"] == 1
        assert run["workspace"] == "normal"
        actual = {item["id"]: item["value"] for item in run["statistics"]["metrics"]}
        for key, value in expected.items():
            assert actual[key] == value
        assert run["usage"]["request_count"] == 0
        assert run["usage"]["mock_calls"] == 6
        assert run["usage"]["total_tokens"] is None
        assert "离线夹具演练" in run["draft_markdown"]
        assert len(run["source_datasets"]) == len(run["outline"]["groups"])
        assert all(item["sha256"] for item in run["source_datasets"])
        assert len(run["events"]) == run["events"][-1]["seq"]
        assert client.get("/api/v1/runs").json()["items"][0]["id"] == run["id"]
        assert (
            client.get("/api/v1/runs", params={"report_id": run["report_id"]}).json()["items"][0][
                "id"
            ]
            == run["id"]
        )
        with connection() as db:
            assert db.execute("SELECT version FROM reports").fetchone()[0] == 1


def test_real_transport_runs_six_bounded_calls_and_persists_only_safe_numeric_usage(build_app):
    factory, _, _ = build_app
    supplier = Supplier()
    app = factory(supplier)
    with TestClient(app) as client:
        run = finished(client, app.state.execution_service, submit(client, mode="live"))
        assert run["status"] == "completed", run
        assert len(supplier.calls) == 6
        assert run["usage"]["request_count"] == 6
        assert run["usage"]["reserved_output_tokens"] == 2752
        assert run["usage"]["total_tokens"] == 90
        assert run["usage"]["reasoning_tokens"] is None
        assert all(call[2]["thinking"] == {"type": "disabled"} for call in supplier.calls)
        assert all(call[2]["max_tokens"] <= 1024 for call in supplier.calls)
        assert "provider_secret" not in json.dumps(run)
        before = len(supplier.calls)
        client.get("/api/v1/runs/" + run["id"])
        client.get("/api/v1/runs")
        assert len(supplier.calls) == before


def test_program_numeric_error_forces_writer_revision_even_when_model_checker_passes(build_app):
    factory, _, _ = build_app
    supplier = Supplier(bad_writer=1)
    app = factory(supplier)
    with TestClient(app) as client:
        run = finished(client, app.state.execution_service, submit(client, mode="live"))
        assert run["status"] == "completed", run
        assert len(run["revision_history"]) == 2
        assert run["revision_history"][0]["review"]["program_passed"] is False
        assert run["revision_history"][0]["review"]["model_passed"] is True
        assert run["revision_history"][1]["review"]["passed"] is True
        assert run["usage"]["request_count"] == 8
        assert "999" not in run["draft_markdown"]
        assert run["nodes"][-1]["role"] == "manager"


def test_two_revisions_are_strictly_bounded_and_never_accepted_as_valid(build_app):
    factory, _, _ = build_app
    supplier = Supplier(bad_writer=100)
    app = factory(supplier)
    with TestClient(app) as client:
        run = finished(client, app.state.execution_service, submit(client, mode="live"))
        assert run["status"] == "review_failed"
        assert supplier.writer_count == 3
        assert len(run["revision_history"]) == 3
        assert run["acceptance"] is None
        assert not any(phase == "acceptance" for _, phase, _ in supplier.calls)


def test_missing_scope_creates_no_report_and_is_findable_in_global_history(build_app):
    factory, connection, _ = build_app
    app = factory()
    with TestClient(app) as client:
        run = finished(client, app.state.execution_service, submit(client, text="帮我写汇报"))
        assert run["status"] == "needs_input"
        assert run["report_id"] is None
        assert run["questions"]
        assert client.get("/api/v1/runs").json()["items"][0]["id"] == run["id"]
        with connection() as db:
            assert db.execute("SELECT COUNT(*) FROM reports").fetchone()[0] == 0


def test_local_api_is_never_called_without_explicit_authorization(build_app):
    factory, _, _ = build_app
    app = factory()
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/runs",
            headers={"Idempotency-Key": "no-source"},
            json=dict(user_text=TECH_TEXT, mode="offline_mock"),
        )
        run = finished(client, app.state.execution_service, response)
        assert run["status"] == "needs_input"
        assert run["source_datasets"] == []
        assert run["statistics"] is None
        assert run["missing_fields"] == ["materials"]


@pytest.mark.parametrize("damage", ["changed", "missing"])
def test_data_reads_files_and_stops_before_writer_when_source_is_damaged(build_app, damage):
    factory, _, materials = build_app
    draft = materials.stage_import(
        (ROOT / "data/demo/technical-q2/项目进度.csv").read_bytes(),
        "项目进度.csv",
        "projects",
        "normal",
    )
    material = materials.confirm(draft["id"], "normal", {"mapping": draft["suggested_mapping"]})
    path = materials.original_path(materials.get(material["id"], "normal"))
    if damage == "changed":
        path.write_bytes(b"changed after import")
    else:
        path.unlink()
    app = factory()
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/runs",
            headers={"Idempotency-Key": "damaged-source"},
            json=dict(user_text=TECH_TEXT, mode="offline_mock", material_ids=[material["id"]]),
        )
        run = finished(client, app.state.execution_service, response)
        assert run["status"] == "failed"
        assert run["error"]["code"] == "material_file"
        assert "Data无法读取" in run["error"]["message"]
        assert [node["role"] for node in run["nodes"]] == ["manager", "planner", "data"]
        assert run["statistics"] is None


@pytest.mark.parametrize(
    "limit,value,expected_calls", [("request_budget", 1, 1), ("output_budget", 256, 1)]
)
def test_each_http_attempt_reserves_persisted_budget_without_retry(
    build_app, limit, value, expected_calls
):
    factory, _, _ = build_app
    supplier = Supplier()
    app = factory(supplier)
    with TestClient(app) as client:
        run = finished(
            client, app.state.execution_service, submit(client, mode="live", **{limit: value})
        )
        assert run["status"] == "failed"
        assert run["error"]["code"] == limit
        assert len(supplier.calls) == expected_calls
        assert run["usage"]["request_count"] == expected_calls
        assert len(run["model_attempts"]) == expected_calls


def test_model_cannot_change_department_outside_user_request(build_app):
    factory, connection, _ = build_app
    supplier = Supplier(bad_scope=True)
    app = factory(supplier)
    with TestClient(app) as client:
        run = finished(client, app.state.execution_service, submit(client, mode="live"))
        assert run["status"] == "failed"
        assert run["error"]["code"] == "ungrounded_department"
        assert run["nodes"][-1]["candidate_output"]["requirements"]["department"] == "行政部"
        assert run["nodes"][-1]["candidate_status"] == "pending_business_validation"
        with connection() as db:
            assert db.execute("SELECT COUNT(*) FROM reports").fetchone()[0] == 0


@pytest.mark.parametrize(
    "phase", ["requirements", "outline", "summary", "draft", "review", "acceptance"]
)
def test_malformed_or_duplicate_json_keys_fail_without_partial_role_success(build_app, phase):
    factory, _, _ = build_app
    app = factory(Supplier(malformed=phase))
    with TestClient(app) as client:
        run = finished(client, app.state.execution_service, submit(client, mode="live"))
        assert run["status"] == "failed"
        assert run["nodes"][-1]["status"] == "failed"
        assert run["acceptance"] is None


def test_idempotency_reuses_same_task_and_different_payload_is_conflict(build_app):
    factory, _, _ = build_app
    app = factory()
    with TestClient(app) as client:
        first = submit(client)
        run = finished(client, app.state.execution_service, first)
        repeated = submit(client)
        assert repeated.status_code == 202
        assert repeated.json()["id"] == run["id"]
        assert repeated.json()["usage"] == run["usage"]
        assert submit(client, text=ADMIN_TEXT).status_code == 409
        assert len(client.get("/api/v1/runs").json()["items"]) == 1


def test_running_cancellation_stops_after_inflight_call_and_queued_cancel_makes_no_call(build_app):
    factory, _, _ = build_app
    supplier = Supplier(blocked="requirements")
    app = factory(supplier)
    with TestClient(app) as client:
        first = submit(client, mode="live")
        assert supplier.entered.wait(2)
        second = submit(client, mode="live", key="second")
        assert second.json()["status"] == "queued"
        assert (
            client.post("/api/v1/runs/" + second.json()["id"] + "/cancel").json()["status"]
            == "cancelled"
        )
        cancelling = client.post("/api/v1/runs/" + first.json()["id"] + "/cancel").json()
        assert cancelling["cancel_requested"]
        supplier.release.set()
        run = finished(client, app.state.execution_service, first)
        assert run["status"] == "cancelled"
        assert len(supplier.calls) == 1
        assert run["usage"]["request_count"] == 1
        assert run["report_id"] is None
        assert client.post("/api/v1/runs/" + run["id"] + "/cancel").json()["status"] == "cancelled"


def test_second_service_cannot_execute_or_interrupt_owner_when_it_closes(build_app):
    factory, _, _ = build_app
    supplier = Supplier(blocked="requirements")
    app = factory(supplier)
    with TestClient(app) as owner:
        response = submit(owner, mode="live")
        assert supplier.entered.wait(2)
        second_app = factory(Supplier())
        with TestClient(second_app) as second:
            assert not second_app.state.execution_service.available
            assert submit(second, key="other").status_code == 503
            assert second.get("/api/v1/runs/" + response.json()["id"]).json()["status"] == "running"
        assert owner.get("/api/v1/runs/" + response.json()["id"]).json()["status"] == "running"
        supplier.release.set()
        assert finished(owner, app.state.execution_service, response)["status"] == "completed"


def test_failed_live_configuration_is_explicit_and_does_not_fall_back_to_mock(build_app):
    factory, _, _ = build_app

    def unavailable():
        raise ConfigurationError("must not leak this private path or key")

    app = factory(settings_factory=unavailable)
    with TestClient(app) as client:
        run = finished(client, app.state.execution_service, submit(client, mode="live"))
        assert run["status"] == "failed"
        assert run["error"]["code"] == "configuration"
        assert run["usage"]["mock_calls"] == 0
        assert "private path" not in json.dumps(run)


def test_workspace_and_unconfirmed_material_ids_are_not_accessible(build_app):
    factory, _, material_service = build_app
    staged = material_service.stage_import(b"test", "notes.txt", "notes", "normal")
    app = factory()
    with TestClient(app) as client:
        run = finished(client, app.state.execution_service, submit(client))
        assert (
            client.get("/api/v1/runs/" + run["id"], headers={"X-Workspace": "demo"}).status_code
            == 404
        )
        assert (
            client.post(
                "/api/v1/runs/" + run["id"] + "/cancel", headers={"X-Workspace": "demo"}
            ).status_code
            == 404
        )
        assert client.get("/api/v1/runs", headers={"X-Workspace": "demo"}).json() == {"items": []}
        assert submit(client, key="bad-material", material_ids=[staged["id"]]).status_code == 404


@pytest.mark.parametrize(
    "bad",
    [
        dict(user_text=""),
        dict(material_ids=["a", "a"]),
        dict(request_budget=True),
        dict(request_budget=13),
        dict(output_budget=5569),
        dict(max_revisions=3),
        dict(mode="mock"),
        dict(report_id="r"),
        dict(expected_version=1),
        dict(use_local_api="yes"),
        dict(unknown="field"),
    ],
)
def test_input_contract_rejects_ambiguous_budget_and_scope(bad):
    values = dict(user_text=TECH_TEXT)
    values.update(bad)
    with pytest.raises(ValueError):
        RunInput.model_validate(values)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("生成2026年第二季度技术部汇报", ("2026-04-01", "2026-07-01")),
        ("2026Q4技术部", ("2026-10-01", "2027-01-01")),
        ("2026年12月技术部", ("2026-12-01", "2027-01-01")),
        ("2026年年度技术部汇报", ("2026-01-01", "2027-01-01")),
        ("2026-04-01至2026-07-01", ("2026-04-01", "2026-07-01")),
    ],
)
def test_only_explicit_periods_ground_scope(text, expected):
    assert expected in _periods(text)
    assert not _periods("本季度工作汇报")


def test_restart_marks_unknown_queued_execution_interrupted_without_replaying_calls(build_app):
    factory, connection, material_service = build_app
    app = factory()
    with TestClient(app) as client:
        run = finished(client, app.state.execution_service, submit(client))
    with connection() as db:
        run["status"] = "running"
        run["usage"]["request_count"] = 1
        run["usage"]["reserved_output_tokens"] = 256
        db.execute(
            "UPDATE execution_runs SET status='running',payload=? WHERE id=?",
            (json.dumps(run), run["id"]),
        )
    supplier = Supplier()
    restarted = factory(supplier)
    with TestClient(restarted) as client:
        current = client.get("/api/v1/runs/" + run["id"]).json()
        assert current["status"] == "interrupted"
        assert current["usage"]["request_count"] == 1
        assert current["usage"]["reserved_output_tokens"] == 256
        assert not supplier.calls
        assert current["error"]["code"] == "server_restarted"
    service = ExecutionService(connection, material_service, None, None, None)
    assert not service.available
    service.close()
    assert TERMINAL >= {"completed", "interrupted", "review_failed"}


def test_existing_report_scope_is_fixed_and_stale_run_cannot_finish(build_app):
    factory, connection, _ = build_app
    supplier = Supplier(blocked="draft")
    app = factory(supplier)
    with connection() as db:
        db.execute(
            "INSERT INTO reports VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "existing",
                "normal",
                "已有标题",
                "技术部",
                "2026-04-01",
                "2026-07-01",
                "已有重点",
                '["概况","成果"]',
                1,
                "draft",
                "now",
                "now",
            ),
        )
    with TestClient(app) as client:
        response = submit(
            client,
            text="请沿用当前报告范围生成",
            mode="live",
            report_id="existing",
            expected_version=1,
        )
        assert supplier.entered.wait(2)
        in_flight = client.get("/api/v1/runs/" + response.json()["id"]).json()
        assert in_flight["requirements"]["department"] == "技术部"
        assert in_flight["requirements"]["sections"] == ["概况", "成果"]
        assert in_flight["usage"]["request_count"] == 4
        assert in_flight["model_attempts"][-1]["status"] == "reserved"
        with connection() as db:
            db.execute("UPDATE reports SET version=2,department='行政部' WHERE id='existing'")
        supplier.release.set()
        run = finished(client, app.state.execution_service, response)
        assert run["status"] == "failed"
        assert run["error"]["code"] == "stale_report"
        assert run["report_version"] == 1
        assert len(supplier.calls) == 4
        assert not run["acceptance"]
        assert (
            submit(client, key="old-version", report_id="existing", expected_version=1).status_code
            == 409
        )


def test_http_failure_has_no_automatic_retries_and_no_provider_body_leak(build_app):
    factory, _, _ = build_app
    calls = []

    def failed(request):
        calls.append(request)
        return httpx.Response(401, text="secret=do-not-persist /Users/private/provider")

    app = factory(failed)
    with TestClient(app) as client:
        run = finished(client, app.state.execution_service, submit(client, mode="live"))
        assert run["status"] == "failed"
        assert run["usage"]["request_count"] == 1
        assert run["usage"]["reserved_output_tokens"] == 256
        assert run["usage"]["total_tokens"] is None
        assert len(calls) == 1
        assert "do-not-persist" not in json.dumps(run)
        assert "/Users/private" not in json.dumps(run)


def test_owned_materials_can_run_without_fixed_api_and_keep_original_authorization(build_app):
    factory, _, material_service = build_app
    material_ids = []
    for filename, kind in (
        ("项目进度.csv", "projects"),
        ("人员考勤.csv", "attendance"),
        ("成果统计.csv", "achievements"),
    ):
        draft = material_service.stage_import(
            (ROOT / "data/demo/technical-q2" / filename).read_bytes(), filename, kind, "normal"
        )
        material_ids.append(
            material_service.confirm(
                draft["id"], "normal", {"mapping": draft["suggested_mapping"]}
            )["id"]
        )
    app = factory()
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/runs",
            headers={"Idempotency-Key": "own-files"},
            json=dict(user_text=TECH_TEXT, mode="offline_mock", material_ids=material_ids),
        )
        run = finished(client, app.state.execution_service, response)
        assert run["status"] == "completed"
        assert run["material_ids"] == material_ids
        assert run["source_datasets"] == []
        planner = next(node for node in run["nodes"] if node["role"] == "planner")
        assert planner["inputs"]["context"]["manager"]["tasks"]
        writer = next(node for node in run["nodes"] if node["role"] == "writer")
        assert writer["inputs"]["context"]["facts"]
        acceptance = run["nodes"][-1]
        assert acceptance["inputs"]["context"]["review"]["passed"]


def test_wrong_quarter_end_is_rejected_and_typed_candidate_remains_inspectable(build_app):
    factory, connection, _ = build_app
    supplier = Supplier()
    hints = []

    def wrong_period(request):
        payload = json.loads(request.content)
        context = json.loads(payload["messages"][1]["content"])
        hints.extend(context["grounded_periods"])
        assert "用户明确要求季度时才换算季度边界" in payload["messages"][0]["content"]
        response = supplier(request)
        data = response.json()
        candidate = json.loads(data["choices"][0]["message"]["content"])
        candidate["requirements"]["end_date"] = "2026-06-30"
        data["choices"][0]["message"]["content"] = json.dumps(candidate, ensure_ascii=False)
        return httpx.Response(200, json=data)

    app = factory(wrong_period)
    with TestClient(app) as client:
        run = finished(client, app.state.execution_service, submit(client, mode="live"))
        assert hints == [dict(start_date="2026-04-01", end_date="2026-07-01")]
        assert run["status"] == "failed"
        assert run["error"]["code"] == "ungrounded_period"
        assert "期间与用户指定日期或材料覆盖范围不一致" in run["error"]["message"]
        node = run["nodes"][0]
        assert node["candidate_output"]["requirements"]["end_date"] == "2026-06-30"
        assert node["candidate_status"] == "pending_business_validation"
        assert node["status"] == "failed"
        assert node["output"] is None
        assert run["requirements"] is None
        assert run["usage"]["request_count"] == 1
        assert run["report_id"] is None
        with connection() as db:
            assert db.execute("SELECT COUNT(*) FROM reports").fetchone()[0] == 0


def test_manager_can_copy_explicit_half_open_hint_and_business_success_validates_candidate(
    build_app,
):
    factory, _, _ = build_app
    supplier = Supplier()

    def copy_period(request):
        response = supplier(request)
        if supplier.calls[-1][1] != "requirements":
            return response
        payload = json.loads(request.content)
        context = json.loads(payload["messages"][1]["content"])
        data = response.json()
        candidate = json.loads(data["choices"][0]["message"]["content"])
        candidate["requirements"].update(context["grounded_periods"][0])
        data["choices"][0]["message"]["content"] = json.dumps(candidate, ensure_ascii=False)
        return httpx.Response(200, json=data)

    app = factory(copy_period)
    with TestClient(app) as client:
        run = finished(client, app.state.execution_service, submit(client, mode="live"))
        assert run["status"] == "completed"
        assert run["requirements"]["end_date"] == "2026-07-01"
        assert run["nodes"][0]["candidate_status"] == "node_completed"
        assert run["nodes"][0]["output"] == run["nodes"][0]["candidate_output"]


def test_cancelled_inflight_response_never_saves_late_typed_candidate(build_app):
    factory, _, _ = build_app
    supplier = Supplier(blocked="requirements")
    app = factory(supplier)
    with TestClient(app) as client:
        response = submit(client, mode="live")
        assert supplier.entered.wait(2)
        client.post("/api/v1/runs/" + response.json()["id"] + "/cancel")
        supplier.release.set()
        run = finished(client, app.state.execution_service, response)
        assert run["status"] == "cancelled"
        assert run["nodes"][0]["output"] is None
        assert "candidate_output" not in run["nodes"][0]
        assert run["usage"]["request_count"] == 1


def test_existing_report_scope_failure_has_separate_static_diagnosis(build_app):
    factory, connection, _ = build_app
    supplier = Supplier()

    def changed_saved(request):
        response = supplier(request)
        data = response.json()
        candidate = json.loads(data["choices"][0]["message"]["content"])
        candidate["requirements"]["sections"] = ["改变后的章节"]
        data["choices"][0]["message"]["content"] = json.dumps(candidate, ensure_ascii=False)
        return httpx.Response(200, json=data)

    with connection() as db:
        db.execute(
            "INSERT INTO reports VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "saved",
                "normal",
                "已有标题",
                "技术部",
                "2026-04-01",
                "2026-07-01",
                "",
                '["概况"]',
                1,
                "draft",
                "now",
                "now",
            ),
        )
    app = factory(changed_saved)
    with TestClient(app) as client:
        run = finished(
            client,
            app.state.execution_service,
            submit(client, mode="live", report_id="saved", expected_version=1),
        )
        assert run["status"] == "failed"
        assert run["error"]["code"] == "saved_context_scope"
        assert "已保存报告" in run["error"]["message"]
        assert run["nodes"][0]["candidate_output"]["requirements"]["sections"] == ["改变后的章节"]
        with connection() as db:
            assert (
                db.execute("SELECT sections FROM reports WHERE id='saved'").fetchone()[0]
                == '["概况"]'
            )


def test_truncated_supplier_reply_stops_without_admitting_candidate(build_app):
    supplier = Supplier()

    def truncated(request):
        response = supplier(request)
        payload = response.json()
        payload["choices"][0]["finish_reason"] = "length"
        return httpx.Response(200, json=payload)

    factory, _, _ = build_app
    app = factory(supplier=truncated)
    with TestClient(app) as client:
        run = finished(client, app.state.execution_service, submit(client, mode="live"))
        assert run["status"] == "failed"
        assert run["error"]["code"] == "response_truncated"
        assert len(supplier.calls) == 1
        assert run["requirements"] is None
        assert run["nodes"][0].get("candidate_output") is None
        assert run["usage"]["request_count"] == 1
        assert run["usage"]["reserved_output_tokens"] == 256


def test_final_manager_gets_full_body_facts_limits_and_unique_sources_without_repeated_hashes(
    build_app,
):
    import hashlib

    factory, _, _ = build_app
    app = factory()
    with TestClient(app) as client:
        run = finished(client, app.state.execution_service, submit(client))
        assert run["status"] == "completed"
        context = run["nodes"][-1]["inputs"]["context"]
        assert context["draft_sha256"] == hashlib.sha256(run["draft_markdown"].encode()).hexdigest()
        assert "## 权威统计与口径" in context["draft_markdown"]
        assert "SHA256" not in context["draft_markdown"]
        assert context["materials"] == run["materials"]
        assert any("季度" in item or "期间" in item for item in context["limitations"])
        assert run["draft_markdown"].startswith(context["draft_markdown"])
        assert "SHA256" in run["draft_markdown"]


def test_writer_revision_receives_previous_draft_and_exact_offending_numeric_fragments(build_app):
    supplier = Supplier(bad_writer=1)
    factory, _, _ = build_app
    app = factory(supplier=supplier)
    with TestClient(app) as client:
        run = finished(client, app.state.execution_service, submit(client, mode="live"))
        assert run["status"] == "completed"
        contexts = [node["inputs"]["context"] for node in run["nodes"] if node["role"] == "writer"]
        assert contexts[0]["previous_narrative"] is None
        assert contexts[1]["previous_narrative"]["sections"][0]["text"] == "项目数量为999个。"
        assert any(
            "999" in issue and "概况" in issue for issue in contexts[1]["previous_review"]["issues"]
        )
