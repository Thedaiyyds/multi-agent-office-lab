"""Delivery tests use temporary databases, deterministic local suppliers and a stub PDF."""

import hashlib
import json
import re
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from threading import Event

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from office_agents.config import Settings
from office_agents.workbench.delivery import create_delivery_router
from office_agents.workbench.demo import load_local_dataset
from office_agents.workbench.execution import create_execution_router
from office_agents.workbench.materials import MaterialService

ROOT = Path(__file__).resolve().parents[1]
TEXT = "生成2026年第二季度技术部工作汇报，包含项目进度、人员考勤、成果统计。"


class LocalSupplier:
    def __init__(self):
        self.calls = []
        self.reject_review = False
        self.reject_acceptance = False
        self.block_phase = None
        self.entered, self.release = Event(), Event()

    def __call__(self, request):
        payload = json.loads(request.content)
        role = re.search(r"ROLE=(\w+)", payload["messages"][0]["content"])[1]
        phase = re.search(r"PHASE=(\w+)", payload["messages"][0]["content"])[1]
        context = json.loads(payload["messages"][1]["content"])
        self.calls.append((role, phase))
        if phase == self.block_phase:
            self.entered.set()
            assert self.release.wait(5), "test must release the bounded local supplier"
        if phase == "requirements":
            result = dict(
                status="ready",
                requirements=dict(
                    title="技术部工作汇报",
                    department="技术部",
                    start_date="2026-04-01",
                    end_date="2026-07-01",
                    focus="",
                    sections=["概况", "成果", "风险", "计划"],
                ),
                tasks=["拆解", "规划", "整理", "撰写", "校验"],
                missing_fields=[],
                questions=[],
            )
        elif role == "planner":
            groups = ["projects", "attendance", "achievements"]
            result = dict(
                groups=groups,
                sections=[
                    dict(title=title, purpose="整理授权数据", groups=groups)
                    for title in context["requirements"]["sections"]
                ],
            )
        elif role == "data":
            result = dict(summary="数据已整理。", limitations=[])
        elif role == "writer":
            result = dict(
                sections=[
                    dict(title=s["title"], text="依据授权事实 [[fact:F001]] 整理本期情况。")
                    for s in context["outline"]["sections"]
                ],
                suggestions=["建议完善后续安排。"],
            )
        elif role == "checker":
            result = dict(
                passed=not self.reject_review,
                issues=["叙述与材料不符"] if self.reject_review else [],
                revision_instructions=["请核对原文"] if self.reject_review else [],
            )
        else:
            result = dict(accepted=not self.reject_acceptance, reasons=["已完成范围和审核校验"])
        return httpx.Response(
            200,
            json=dict(
                choices=[
                    dict(
                        message=dict(
                            role="assistant", content=json.dumps(result, ensure_ascii=False)
                        ),
                        finish_reason="stop",
                    )
                ],
                usage=dict(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            ),
        )


class PdfStub:
    def __init__(self):
        self.snapshots = []
        self.fail = False

    def __call__(self, snapshot, destination):
        self.snapshots.append(snapshot)
        if self.fail:
            raise RuntimeError("private/server/path or provider secret must never escape")
        destination.write_bytes(b"%PDF-1.4\n" + snapshot["markdown"].encode() + b"\n%%EOF")


@pytest.fixture
def app_factory(tmp_path):
    database = tmp_path / "delivery.sqlite3"
    renderer = PdfStub()
    supplier = LocalSupplier()

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
        db.execute("""CREATE TABLE reports(id TEXT PRIMARY KEY,workspace TEXT,title TEXT,
            department TEXT,start_date TEXT,end_date TEXT,focus TEXT,sections TEXT,
            version INTEGER,status TEXT CHECK(status='draft'),created_at TEXT,updated_at TEXT)""")
    material_service = MaterialService(connection, tmp_path / "materials")

    def factory():
        app = FastAPI()
        execution_router = create_execution_router(
            connection,
            material_service,
            settings_factory=lambda: Settings(
                base_url="https://test.invalid/v1", model="test", api_key="test-only"
            ),
            transport=httpx.MockTransport(supplier),
            local_provider=lambda kind: load_local_dataset(ROOT / "data/demo", kind),
        )
        app.include_router(execution_router)
        delivery_router = create_delivery_router(
            connection,
            execution_router.execution_service,
            tmp_path / "delivery",
            render_pdf=renderer,
        )
        app.include_router(delivery_router)
        app.state.execution_service = execution_router.execution_service
        app.state.delivery_service = delivery_router.delivery_service
        return app

    return factory, connection, renderer, supplier


def wait_run(client, app, response):
    assert response.status_code == 202, response.text
    run_id = response.json()["id"]
    assert app.state.execution_service.wait_for_idle(5)
    for _ in range(100):
        run = client.get("/api/v1/runs/" + run_id).json()
        items = (
            client.get(f"/api/v1/reports/{run['report_id']}/revisions").json()["items"]
            if run["report_id"]
            else []
        )
        if items and not any(
            item["status"] == "reviewing"
            or (
                item["status"] == "approved"
                and any(
                    artifact["state"] in {"missing", "running"} for artifact in item["artifacts"]
                )
            )
            for item in items
        ):
            if run.get("run_type") != "revision_review" or any(
                item["review_run_id"] == run_id for item in items
            ):
                return run, items
        time.sleep(0.01)
    raise AssertionError("delivery callback did not finish")


def initial(client, app, mode="offline_mock", key="initial"):
    return wait_run(
        client,
        app,
        client.post(
            "/api/v1/runs",
            headers={"Idempotency-Key": key},
            json=dict(user_text=TEXT, mode=mode, use_local_api=True),
        ),
    )


def changed(client, run, base, *, text="依据授权事实 [[fact:F001]] 重新说明工作安排。"):
    narrative = json.loads(
        json.dumps(
            client.get(f"/api/v1/reports/{run['report_id']}/revisions/{base['id']}").json()[
                "snapshot"
            ]["narrative"]
        )
    )
    narrative["sections"][0]["text"] = text
    return client.post(
        f"/api/v1/reports/{run['report_id']}/revisions",
        json=dict(
            expected_report_version=run["report_version"],
            expected_revision_id=base["id"],
            narrative=narrative,
        ),
    )


def revision_url(run, revision):
    return f"/api/v1/reports/{run['report_id']}/revisions/{revision['id']}"


def test_accepted_execution_automatically_captures_and_exports_same_snapshot(app_factory):
    factory, connection, renderer, supplier = app_factory
    app = factory()
    with TestClient(app) as client:
        run, items = initial(client, app)
        assert run["status"] == "completed"
        assert len(items) == 1
        base = items[0]
        assert base["status"] == "approved" and base["current"]
        url = revision_url(run, base)
        detail = client.get(url).json()
        md = client.get(url + "/exports/md")
        pdf = client.get(url + "/exports/pdf")
        assert md.status_code == pdf.status_code == 200
        assert md.text == detail["snapshot"]["markdown"] == run["draft_markdown"]
        assert renderer.snapshots[0] == detail["snapshot"]
        assert pdf.headers["x-report-snapshot"] == base["content_hash"]
        assert pdf.headers["x-artifact-sha256"] == hashlib.sha256(pdf.content).hexdigest()
        assert md.headers["x-report-current"] == "true"
        assert "离线夹具" in md.text
        assert supplier.calls == []
        app.state.delivery_service.record_run(run)
        assert len(client.get(f"/api/v1/reports/{run['report_id']}/revisions").json()["items"]) == 1
        assert len(renderer.snapshots) == 1
        with connection() as db:
            assert db.execute("SELECT status FROM reports").fetchone()[0] == "draft"


def test_edit_invalidates_current_approval_and_preserves_old_download(app_factory):
    factory, _, _, _ = app_factory
    app = factory()
    with TestClient(app) as client:
        run, items = initial(client, app)
        old = items[0]
        response = changed(client, run, old)
        assert response.status_code == 201, response.text
        new = response.json()
        assert new["number"] == 2 and new["current"] and new["status"] == "needs_review"
        assert new["content_hash"] != old["content_hash"]
        assert new["review"] is new["acceptance"] is None
        assert client.get(revision_url(run, new) + "/exports/md").status_code == 409
        assert client.post(revision_url(run, new) + "/exports").status_code == 409
        old_file = client.get(revision_url(run, old) + "/exports/md")
        assert old_file.status_code == 200 and old_file.headers["x-report-current"] == "false"
        assert changed(client, run, old).status_code == 409


@pytest.mark.parametrize(
    "text",
    ["共有999个项目。", "引用 [[fact:F999]]", "<script>bad</script>", "第三季度有五项成果。"],
)
def test_invalid_narrative_never_creates_revision(app_factory, text):
    factory, _, _, _ = app_factory
    app = factory()
    with TestClient(app) as client:
        run, items = initial(client, app)
        response = changed(client, run, items[0], text=text)
        assert response.status_code == 422
        assert len(client.get(f"/api/v1/reports/{run['report_id']}/revisions").json()["items"]) == 1


def test_revision_input_rejects_facts_injection_and_section_scope_changes(app_factory):
    factory, _, _, _ = app_factory
    app = factory()
    with TestClient(app) as client:
        run, items = initial(client, app)
        base = items[0]
        narrative = client.get(revision_url(run, base)).json()["snapshot"]["narrative"]
        body = dict(
            expected_report_version=1,
            expected_revision_id=base["id"],
            narrative=narrative,
            facts=[{"id": "F001", "value": 999}],
        )
        assert (
            client.post(f"/api/v1/reports/{run['report_id']}/revisions", json=body).status_code
            == 422
        )
        body.pop("facts")
        narrative["sections"][0]["title"] = "偷偷修改章节"
        assert (
            client.post(f"/api/v1/reports/{run['report_id']}/revisions", json=body).status_code
            == 422
        )


def test_live_re_review_calls_only_checker_and_manager_with_same_facts(app_factory):
    factory, _, _, supplier = app_factory
    app = factory()
    with TestClient(app) as client:
        run, items = initial(client, app, mode="live")
        assert len(supplier.calls) == 6
        new = changed(client, run, items[0]).json()
        url = revision_url(run, new)
        response = client.post(url + "/review", headers={"Idempotency-Key": "review"}, json={})
        review_run, revisions = wait_run(client, app, response)
        assert review_run["status"] == "completed"
        assert supplier.calls[6:] == [("checker", "review"), ("manager", "acceptance")]
        assert review_run["usage"]["request_count"] == 2
        assert review_run["usage"]["reserved_output_tokens"] == 512
        detail = client.get(url).json()
        assert detail["status"] == "approved" and detail["current"]
        assert detail["snapshot"] == new["snapshot"]
        assert detail["review_attempts"][-1]["content_hash"] == new["content_hash"]
        repeated = client.post(url + "/review", headers={"Idempotency-Key": "review"}, json={})
        assert repeated.status_code == 202 and repeated.json()["id"] == review_run["id"]
        assert len(supplier.calls) == 8
        assert client.get(url + "/exports/pdf").status_code == 200


@pytest.mark.parametrize("checker_reject,manager_reject", [(True, False), (False, True)])
def test_rejected_re_review_never_exports_qualified_document(
    app_factory, checker_reject, manager_reject
):
    factory, _, _, supplier = app_factory
    app = factory()
    with TestClient(app) as client:
        run, items = initial(client, app, mode="live")
        new = changed(client, run, items[0]).json()
        supplier.reject_review, supplier.reject_acceptance = checker_reject, manager_reject
        url = revision_url(run, new)
        review_run, _ = wait_run(
            client,
            app,
            client.post(url + "/review", headers={"Idempotency-Key": "rejected"}, json={}),
        )
        assert review_run["status"] == "review_failed"
        detail = client.get(url).json()
        assert detail["status"] == "needs_changes" and detail["current"]
        assert client.get(url + "/exports/md").status_code == 409
        assert ("writer", "draft") not in supplier.calls[6:]
        supplier.reject_review = supplier.reject_acceptance = False
        second, _ = wait_run(
            client, app, client.post(url + "/review", headers={"Idempotency-Key": "retry"}, json={})
        )
        assert second["status"] == "completed"
        assert len(client.get(url).json()["review_attempts"]) == 2


def test_export_failure_retry_does_not_repeat_models(app_factory):
    factory, _, renderer, supplier = app_factory
    renderer.fail = True
    app = factory()
    with TestClient(app) as client:
        run, items = initial(client, app, mode="live")
        url = revision_url(run, items[0])
        response = client.get(url).json()
        assert response["status"] == "approved"
        assert {item["format"]: item["state"] for item in response["artifacts"]} == {
            "md": "ready",
            "pdf": "failed",
        }
        assert "private/" not in json.dumps(response)
        assert client.get(url + "/exports/md").status_code == 200
        assert client.get(url + "/exports/pdf").status_code == 409
        calls = list(supplier.calls)
        renderer.fail = False
        recovered = client.post(url + "/exports")
        assert recovered.status_code == 200
        assert all(item["state"] == "ready" for item in recovered.json()["artifacts"])
        assert supplier.calls == calls
        assert client.get(url + "/exports/pdf").status_code == 200


def test_file_corruption_blocks_download_and_retry_regenerates(app_factory):
    factory, connection, _, supplier = app_factory
    app = factory()
    with TestClient(app) as client:
        run, items = initial(client, app)
        url = revision_url(run, items[0])
        with connection() as db:
            row = db.execute(
                "SELECT relative_path FROM report_artifacts WHERE format='md'"
            ).fetchone()
        path = app.state.delivery_service.root / row[0]
        path.write_text("altered report")
        assert client.get(url + "/exports/md").status_code == 409
        assert client.get(url).json()["artifacts"][0]["state"] == "failed"
        assert client.post(url + "/exports").status_code == 200
        assert client.get(url + "/exports/md").text == run["draft_markdown"]
        assert supplier.calls == []


def test_workspace_isolation_and_stale_scope_protects_review(app_factory):
    factory, connection, _, _ = app_factory
    app = factory()
    with TestClient(app) as client:
        run, items = initial(client, app)
        url = revision_url(run, items[0])
        for suffix in ("", "/exports", "/exports/md", "/exports/pdf"):
            assert client.get(url + suffix, headers={"X-Workspace": "demo"}).status_code == 404
        assert (
            client.get(
                f"/api/v1/reports/{run['report_id']}/revisions", headers={"X-Workspace": "demo"}
            ).status_code
            == 404
        )
        new = changed(client, run, items[0]).json()
        with connection() as db:
            db.execute("UPDATE reports SET version=version+1 WHERE id=?", (run["report_id"],))
        assert client.get(revision_url(run, items[0]) + "/exports/md").status_code == 200
        assert not client.get(revision_url(run, items[0])).json()["current"]
        response = client.post(
            revision_url(run, new) + "/review", headers={"Idempotency-Key": "stale"}, json={}
        )
        assert response.status_code == 409


def test_restart_preserves_revisions_and_repairs_missing_exports_without_model(app_factory):
    factory, _, renderer, supplier = app_factory
    app = factory()
    with TestClient(app) as client:
        run, items = initial(client, app)
        url = revision_url(run, items[0])
        app.state.delivery_service.download(
            run["report_id"], items[0]["id"], "normal", "pdf"
        ).path.unlink()
    renderer.snapshots.clear()
    app = factory()
    with TestClient(app) as client:
        assert client.get(url + "/exports/pdf").status_code == 200
        assert len(renderer.snapshots) == 1
        assert supplier.calls == []
        assert len(client.get(f"/api/v1/reports/{run['report_id']}/revisions").json()["items"]) == 1


def test_snapshot_tamper_rejected_even_when_file_still_matches(app_factory):
    factory, connection, _, _ = app_factory
    app = factory()
    with TestClient(app) as client:
        run, items = initial(client, app)
        revision = items[0]
        url = revision_url(run, revision)
        with connection() as db:
            payload = json.loads(
                db.execute(
                    "SELECT payload FROM report_revisions WHERE id=?", (revision["id"],)
                ).fetchone()[0]
            )
            payload["snapshot"]["facts"][0]["value"] = 999
            db.execute(
                "UPDATE report_revisions SET payload=? WHERE id=?",
                (json.dumps(payload), revision["id"]),
            )
        assert client.get(url).status_code == 409
        assert client.get(url + "/exports/md").status_code == 409
        assert client.post(url + "/exports").status_code == 409


def test_queued_review_cancel_updates_revision_without_starting_paid_nodes(app_factory):
    factory, _, _, supplier = app_factory
    app = factory()
    with TestClient(app) as client:
        run, items = initial(client, app, mode="live")
        new = changed(client, run, items[0]).json()
        supplier.block_phase = "requirements"
        busy = client.post(
            "/api/v1/runs",
            headers={"Idempotency-Key": "busy"},
            json=dict(user_text=TEXT, mode="live", use_local_api=True),
        )
        assert busy.status_code == 202
        try:
            assert supplier.entered.wait(3)
            queued = client.post(
                revision_url(run, new) + "/review",
                headers={"Idempotency-Key": "queued-review"},
                json={},
            )
            assert queued.status_code == 202
            review_id = queued.json()["id"]
            assert client.get("/api/v1/runs/" + review_id).json()["status"] == "queued"
            cancelled = client.post("/api/v1/runs/" + review_id + "/cancel")
            assert cancelled.status_code == 200
            assert cancelled.json()["status"] == "cancelled"
            revision = client.get(revision_url(run, new)).json()
            assert revision["status"] == "needs_changes"
            assert revision["review_attempts"][-1]["usage"]["request_count"] == 0
            assert len(supplier.calls) == 7
        finally:
            supplier.release.set()
        assert app.state.execution_service.wait_for_idle(5)
        final = client.get("/api/v1/runs/" + review_id).json()
        assert final["nodes"] == [] and final["usage"]["request_count"] == 0
        assert client.get(revision_url(run, new) + "/exports/md").status_code == 409
