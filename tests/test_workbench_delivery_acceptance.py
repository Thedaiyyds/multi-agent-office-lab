"""Independent delivery acceptance through normal API calls, never paid models."""

import hashlib
import json
import re
import time
from contextlib import contextmanager
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from threading import Event
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from office_agents.config import Settings
from office_agents.workbench.api import create_app

SAMPLES = Path(__file__).resolve().parents[1] / "data/demo"
TERMINAL = {"completed", "needs_input", "failed", "review_failed", "cancelled", "interrupted"}


class Provider:
    """Local scripted HTTP edge; deliberately approving to exercise program gates."""

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
            department = "行政部" if "行政部" in context["user_text"] else "技术部"
            reply = {
                "status": "ready",
                "requirements": dict(
                    title=department + "工作汇报",
                    department=department,
                    **context["grounded_periods"][0],
                    focus="依据授权材料说明情况",
                    sections=["工作概况", "主要成果", "问题与风险", "后续计划"],
                ),
                "tasks": ["规划", "整理", "撰写", "审核"],
                "missing_fields": [],
                "questions": [],
            }
        elif phase == "outline":
            groups = (
                ["satisfaction"]
                if context["requirements"]["department"] == "行政部"
                else ["projects", "attendance", "achievements"]
            )
            reply = {
                "sections": [
                    dict(title=title, purpose="整理授权事实", groups=groups)
                    for title in context["requirements"]["sections"]
                ],
                "groups": groups,
            }
        elif phase == "summary":
            reply = dict(summary="已按大纲整理，数值以程序统计为准。", limitations=[])
        elif phase == "draft":
            refs = " ".join(
                "[[fact:" + fact["id"] + "]]"
                for fact in context["facts"]
                if fact["value"] is not None
            )
            reply = dict(
                sections=[
                    dict(
                        title=section["title"],
                        text="依据所选材料整理。" + (refs if index == 0 else "结论限于样本。"),
                    )
                    for index, section in enumerate(context["outline"]["sections"])
                ],
                suggestions=["建议持续补充记录并核对来源。"],
            )
        elif phase == "review":
            reply = dict(passed=True, issues=[], revision_instructions=[])
        elif phase == "acceptance":
            reply = dict(accepted=True, reasons=["已核对本次正文与审核"])
        else:
            raise AssertionError((role, phase))
        if self.mutate:
            result = self.mutate(role, phase, context, reply)
            if isinstance(result, httpx.Response):
                return result
            if result is not None:
                reply = result
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps(reply)}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
            },
        )


@contextmanager
def workbench(tmp_path, provider=None):
    provider = provider or Provider()
    app = create_app(
        database_path=tmp_path / "delivery.sqlite3",
        static_dir=False,
        execution_options={
            "transport": httpx.MockTransport(provider),
            "settings_factory": lambda: Settings(
                base_url="https://local-acceptance.invalid/v1",
                model="local-scripted-fixture",
                api_key="not-a-real-key",
                max_retries=0,
            ),
        },
    )
    with TestClient(app) as client:
        yield client, provider


def wait_run(client, run_id):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        response = client.get("/api/v1/runs/" + run_id)
        assert response.status_code == 200, response.text
        run = response.json()
        if run["status"] in TERMINAL:
            return run
        time.sleep(0.01)
    raise AssertionError("Local fixture did not terminate")


def revision_url(report_id, revision_id=None):
    return (
        "/api/v1/reports/" + report_id + "/revisions" + ("/" + revision_id if revision_id else "")
    )


def create_approved(client, department="技术部"):
    administrative = department == "行政部"
    case = "administration-q1" if administrative else "technical-q2"
    files = (
        [("满意度.csv", "satisfaction")]
        if administrative
        else [
            ("项目进度.csv", "projects"),
            ("人员考勤.csv", "attendance"),
            ("成果统计.csv", "achievements"),
        ]
    )
    ids = []
    for name, kind in files:
        response = client.post(
            "/api/v1/materials/import",
            data={"kind": kind},
            files={"file": (name, (SAMPLES / case / name).read_bytes())},
        )
        assert response.status_code == 201, response.text
        staged = response.json()
        confirmed = client.post(
            "/api/v1/imports/" + staged["id"] + "/confirm",
            json={"mapping": staged["suggested_mapping"]},
        )
        assert confirmed.status_code == 200, confirmed.text
        ids.append(confirmed.json()["id"])
    response = client.post(
        "/api/v1/runs",
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "user_text": (
                "生成2026年第一季度行政部工作汇报，重点行政服务满意度，导出Markdown和PDF。"
                if administrative
                else "生成2026年第二季度技术部工作汇报，包含项目、考勤和成果，导出Markdown和PDF。"
            ),
            "mode": "live",
            "material_ids": ids,
        },
    )
    assert response.status_code == 202, response.text
    run = wait_run(client, response.json()["id"])
    assert run["status"] == "completed", run
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        response = client.get(revision_url(run["report_id"]))
        assert response.status_code == 200, response.text
        items = response.json()["items"]
        if items and all(item["state"] in {"ready", "failed"} for item in items[0]["artifacts"]):
            detail = client.get(revision_url(run["report_id"], items[0]["id"]))
            assert detail.status_code == 200, detail.text
            return run, detail.json()
        time.sleep(0.01)
    raise AssertionError("Approved report did not get its automatic delivery snapshot")


def edit(client, revision, **changes):
    narrative = deepcopy(revision["snapshot"]["narrative"])
    narrative["sections"][0]["text"] += "请结合材料限制理解这些结果。"
    return client.post(
        revision_url(revision["report_id"]),
        json={
            "expected_report_version": revision["report_version"],
            "expected_revision_id": revision["id"],
            "narrative": narrative,
            **changes,
        },
    )


def review(client, revision, *, key=None, **changes):
    return client.post(
        revision_url(revision["report_id"], revision["id"]) + "/review",
        headers={"Idempotency-Key": key or str(uuid4())},
        json=changes,
    )


def download(client, revision, format="md", **options):
    return client.get(
        revision_url(revision["report_id"], revision["id"]) + "/exports/" + format, **options
    )


@pytest.mark.parametrize("department", ["技术部", "行政部"])
def test_auto_delivery_binds_readable_md_and_pdf_to_the_same_reviewed_snapshot(
    tmp_path, department
):
    with workbench(tmp_path) as (client, provider):
        run, revision = create_approved(client, department)
        assert revision["status"] == "approved"
        assert revision["current"] is True
        assert revision["source_run_id"] == run["id"]
        assert revision["review"]["passed"] and revision["acceptance"]["accepted"]
        snapshot = revision["snapshot"]
        expected_hash = hashlib.sha256(
            json.dumps(
                snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode()
        ).hexdigest()
        assert revision["content_hash"] == expected_hash
        assert snapshot["markdown"] == run["draft_markdown"]
        artifacts = {item["format"]: item for item in revision["artifacts"]}
        calls = len(provider.calls)
        md, pdf = download(client, revision), download(client, revision, "pdf")
        assert md.status_code == pdf.status_code == 200, (md.text, pdf.text[:200])
        assert md.content == snapshot["markdown"].encode()
        assert pdf.content.startswith(b"%PDF-")
        reader = PdfReader(BytesIO(pdf.content))
        text = "\n".join(page.extract_text() for page in reader.pages)
        assert department + "工作汇报" in text
        assert snapshot["requirements"]["start_date"] in text
        assert "数据限制与来源" in text
        assert "4.00" in text or "4" in text
        descriptors = []
        for page in reader.pages:
            for reference in page["/Resources"]["/Font"].values():
                font = reference.get_object()
                candidates = [font] + [
                    item.get_object() for item in font.get("/DescendantFonts", [])
                ]
                descriptors.extend(
                    candidate["/FontDescriptor"].get_object()
                    for candidate in candidates
                    if "/FontDescriptor" in candidate
                )
        assert any(
            key in descriptor and descriptor[key].get_object().get_data()
            for descriptor in descriptors
            for key in ("/FontFile", "/FontFile2", "/FontFile3")
        )
        for fmt, content in (("md", md.content), ("pdf", pdf.content)):
            assert artifacts[fmt]["state"] == "ready"
            assert artifacts[fmt]["snapshot_hash"] == expected_hash
            assert artifacts[fmt]["file_sha256"] == hashlib.sha256(content).hexdigest()
            assert artifacts[fmt]["byte_size"] == len(content)
        assert len(provider.calls) == calls == 6
        assert "/Users/" not in md.text
        assert "not-a-real-key" not in md.text


def wait_revision(client, revision, status):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        response = client.get(revision_url(revision["report_id"], revision["id"]))
        assert response.status_code == 200, response.text
        detail = response.json()
        if detail["status"] == status and (
            status != "approved"
            or all(item["state"] in {"ready", "failed"} for item in detail["artifacts"])
        ):
            return detail
        time.sleep(0.01)
    raise AssertionError("Expected local revision status: " + status)


def test_edit_is_a_new_unapproved_snapshot_then_two_roles_reapprove_without_regeneration(tmp_path):
    with workbench(tmp_path) as (client, provider):
        original_run, original = create_approved(client)
        old_md, old_pdf = (
            download(client, original).content,
            download(client, original, "pdf").content,
        )
        response = edit(client, original)
        assert response.status_code == 201, response.text
        changed = response.json()
        assert changed["number"] == original["number"] + 1
        assert changed["status"] == "needs_review"
        assert changed["review"] is None and changed["acceptance"] is None
        assert changed["content_hash"] != original["content_hash"]
        assert changed["snapshot"]["facts"] == original["snapshot"]["facts"]
        assert changed["snapshot"]["materials"] == original["snapshot"]["materials"]
        assert download(client, changed).status_code == 409
        assert (
            client.post(revision_url(changed["report_id"], changed["id"]) + "/exports").status_code
            == 409
        )
        historical = download(client, original)
        assert historical.content == old_md
        assert historical.headers["X-Report-Current"] == "false"
        assert download(client, original, "pdf").content == old_pdf
        key = str(uuid4())
        started = review(client, changed, key=key)
        assert started.status_code == 202, started.text
        run = wait_run(client, started.json()["id"])
        assert run["status"] == "completed", run
        assert [node["role"] for node in run["nodes"]] == ["checker", "manager"]
        assert [call[:2] for call in provider.calls[6:]] == [
            ("checker", "review"),
            ("manager", "acceptance"),
        ]
        assert run["usage"]["request_count"] == 2
        assert run["usage"]["reserved_output_tokens"] == 512
        assert run["usage"]["total_tokens"] == 60
        assert run["material_ids"] == original_run["material_ids"]
        approved = wait_revision(client, changed, "approved")
        assert approved["content_hash"] == changed["content_hash"]
        assert approved["review_attempts"][-1]["content_hash"] == changed["content_hash"]
        assert approved["review_attempts"][-1]["usage"] == run["usage"]
        new_md = download(client, approved)
        assert new_md.status_code == 200
        assert new_md.headers["X-Report-Current"] == "true"
        assert new_md.content == changed["snapshot"]["markdown"].encode()
        assert new_md.content != old_md
        repeated = review(client, changed, key=key)
        assert repeated.status_code == 202
        assert repeated.json()["id"] == run["id"]
        assert len(provider.calls) == 8
        assert review(client, changed, key=key, request_budget=1).status_code == 409
        assert review(client, changed).status_code == 409
        assert len(client.get(revision_url(original["report_id"])).json()["items"]) == 2


@pytest.mark.parametrize("bad", ["number", "reference", "sections", "html", "fact_override"])
def test_invalid_edits_cannot_reuse_approval_or_change_authoritative_facts(tmp_path, bad):
    with workbench(tmp_path) as (client, provider):
        _, original = create_approved(client)
        narrative = deepcopy(original["snapshot"]["narrative"])
        extra = {}
        if bad == "number":
            narrative["sections"][0]["text"] += "完成999个项目。"
        elif bad == "reference":
            narrative["sections"][0]["text"] += "[[fact:F999]]"
        elif bad == "sections":
            narrative["sections"].pop()
        elif bad == "html":
            narrative["sections"][0]["text"] += '<img src="https://external.invalid/pixel">'
        else:
            extra = {"facts": [], "markdown": "替换权威数值"}
        response = edit(client, original, narrative=narrative, **extra)
        assert response.status_code == 422, response.text
        listing = client.get(revision_url(original["report_id"])).json()
        assert len(listing["items"]) == 1
        assert listing["current_revision_id"] == original["id"]
        assert len(provider.calls) == 6
        assert download(client, original).content == original["snapshot"]["markdown"].encode()


@pytest.mark.parametrize("reject_phase", ["review", "acceptance"])
def test_model_rejection_cannot_publish_edited_report_and_old_approval_stays_historical(
    tmp_path, reject_phase
):
    provider = Provider()
    with workbench(tmp_path, provider) as (client, _):
        _, original = create_approved(client)
        changed = edit(client, original).json()

        def reject(role, phase, context, reply):
            if phase == reject_phase:
                return (
                    dict(
                        passed=False,
                        issues=["需补充材料解释"],
                        revision_instructions=["请调整叙述"],
                    )
                    if phase == "review"
                    else dict(accepted=False, reasons=["尚不满足汇报目标"])
                )
            return reply

        provider.mutate = reject
        started = review(client, changed)
        assert started.status_code == 202, started.text
        run = wait_run(client, started.json()["id"])
        assert run["status"] == "review_failed"
        revised = wait_revision(client, changed, "needs_changes")
        assert revised["status"] != "approved"
        assert download(client, revised).status_code == 409
        assert len(provider.calls) == (7 if reject_phase == "review" else 8)
        assert download(client, original).status_code == 200
        assert download(client, original).headers["X-Report-Current"] == "false"


def test_review_budget_is_reserved_and_failed_attempt_can_only_be_retried_explicitly(tmp_path):
    with workbench(tmp_path) as (client, provider):
        _, original = create_approved(client)
        changed = edit(client, original).json()
        key = str(uuid4())
        started = review(client, changed, key=key, request_budget=1)
        assert started.status_code == 202, started.text
        failed = wait_run(client, started.json()["id"])
        assert failed["status"] == "failed"
        assert failed["error"]["code"] == "request_budget"
        assert failed["usage"]["request_count"] == 1
        assert failed["usage"]["reserved_output_tokens"] == 256
        assert failed["acceptance"] is None
        wait_revision(client, changed, "needs_changes")
        repeated = review(client, changed, key=key, request_budget=1)
        assert repeated.json()["id"] == failed["id"]
        assert len(provider.calls) == 7
        retry = review(client, changed)
        assert retry.status_code == 202, retry.text
        completed = wait_run(client, retry.json()["id"])
        assert completed["status"] == "completed"
        approved = wait_revision(client, changed, "approved")
        assert len(approved["review_attempts"]) == 2
        assert [attempt["usage"]["request_count"] for attempt in approved["review_attempts"]] == [
            1,
            2,
        ]
        assert len(provider.calls) == 9


def test_cross_workspace_delivery_routes_never_expose_or_modify_normal_reports(tmp_path):
    with workbench(tmp_path) as (client, provider):
        _, original = create_approved(client)
        headers = {"X-Workspace": "demo", "Idempotency-Key": str(uuid4())}
        base = revision_url(original["report_id"], original["id"])
        for method, path, body in [
            ("GET", revision_url(original["report_id"]), None),
            ("GET", base, None),
            ("GET", base + "/exports", None),
            ("GET", base + "/exports/md", None),
            ("GET", base + "/exports/pdf", None),
            ("POST", base + "/exports", None),
            ("POST", base + "/review", {}),
            (
                "POST",
                revision_url(original["report_id"]),
                {
                    "expected_report_version": original["report_version"],
                    "expected_revision_id": original["id"],
                    "narrative": original["snapshot"]["narrative"],
                },
            ),
        ]:
            response = client.request(method, path, headers=headers, json=body)
            assert response.status_code == 404, (method, path, response.text)
        assert len(provider.calls) == 6
        assert (
            client.get(revision_url(original["report_id"])).json()["current_revision_id"]
            == original["id"]
        )


@pytest.mark.parametrize("format", ["md", "pdf"])
def test_corrupt_artifact_is_blocked_then_safely_regenerated_from_snapshot_without_models(
    tmp_path, format
):
    with workbench(tmp_path) as (client, provider):
        _, original = create_approved(client)
        baseline = download(client, original, format)
        assert baseline.status_code == 200, baseline.text
        matches = list(tmp_path.rglob("report." + format))
        assert len(matches) == 1
        matches[0].write_bytes(b"CORRUPTED_ARTIFACT")
        blocked = download(client, original, format)
        assert blocked.status_code == 409
        assert b"CORRUPTED_ARTIFACT" not in blocked.content
        regenerated = client.post(revision_url(original["report_id"], original["id"]) + "/exports")
        assert regenerated.status_code == 200, regenerated.text
        assert regenerated.json()["content_hash"] == original["content_hash"]
        recovered = download(client, original, format)
        assert recovered.status_code == 200, recovered.text
        assert recovered.headers["X-Report-Snapshot"] == original["content_hash"]
        assert (
            recovered.headers["X-Artifact-SHA256"] == hashlib.sha256(recovered.content).hexdigest()
        )
        if format == "md":
            assert recovered.content == baseline.content
        else:
            assert "技术部工作汇报" in "".join(
                page.extract_text() for page in PdfReader(BytesIO(recovered.content)).pages
            )
        assert len(provider.calls) == 6
        assert len(client.get(revision_url(original["report_id"])).json()["items"]) == 1


def test_stale_edit_and_scope_changes_cannot_reapprove_an_obsolete_revision(tmp_path):
    with workbench(tmp_path) as (client, provider):
        run, original = create_approved(client)
        approved_ids = {
            item["id"] for item in client.get("/api/v1/reports?status=approved").json()["items"]
        }
        assert run["report_id"] in approved_ids
        changed = edit(client, original).json()
        pending_ids = {
            item["id"]
            for item in client.get("/api/v1/reports?status=pending_review").json()["items"]
        }
        assert run["report_id"] in pending_ids
        assert edit(client, original).status_code == 409
        report = client.get("/api/v1/reports/" + run["report_id"]).json()
        fields = {
            key: report[key]
            for key in ("title", "department", "start_date", "end_date", "focus", "sections")
        }
        update = client.patch(
            "/api/v1/reports/" + run["report_id"] + "/draft",
            json={**fields, "focus": "已改变需求重点", "expected_version": report["version"]},
        )
        assert update.status_code == 200, update.text
        assert update.json()["status"] == "draft"
        assert client.get("/api/v1/reports/" + run["report_id"]).json()["status"] == "draft"
        listed = client.get("/api/v1/reports").json()["items"]
        assert next(item for item in listed if item["id"] == run["report_id"])["status"] == "draft"
        draft_ids = {
            item["id"] for item in client.get("/api/v1/reports?status=draft").json()["items"]
        }
        assert run["report_id"] in draft_ids
        assert client.get("/api/v1/reports?status=approved").json()["items"] == []
        assert client.get("/api/v1/reports?status=pending_review").json()["items"] == []
        assert review(client, changed).status_code == 409
        assert edit(client, changed).status_code == 409
        listing = client.get(revision_url(run["report_id"])).json()
        assert listing["current_revision_id"] is None
        historical = download(client, original)
        assert historical.status_code == 200
        assert historical.headers["X-Report-Current"] == "false"
        assert len(provider.calls) == 6


def test_cancellation_during_revised_manager_acceptance_cannot_publish_late_success(tmp_path):
    entered, release = Event(), Event()
    provider = Provider()
    with workbench(tmp_path, provider) as (client, _):
        _, original = create_approved(client)
        changed = edit(client, original).json()

        def blocked(role, phase, context, reply):
            if phase == "acceptance":
                entered.set()
                assert release.wait(5)
            return reply

        provider.mutate = blocked
        started = review(client, changed)
        assert started.status_code == 202, started.text
        run_id = started.json()["id"]
        try:
            assert entered.wait(3)
            current = client.get("/api/v1/runs/" + run_id).json()
            assert current["usage"]["request_count"] == 2
            assert download(client, changed).status_code == 409
            assert edit(client, changed).status_code == 409
            cancel = client.post("/api/v1/runs/" + run_id + "/cancel")
            assert cancel.status_code == 200
        finally:
            release.set()
        run = wait_run(client, run_id)
        assert run["status"] == "cancelled"
        assert run["acceptance"] is None
        final = wait_revision(client, changed, "needs_changes")
        assert final["acceptance"] is None
        assert download(client, final).status_code == 409
        assert len(provider.calls) == 8


def test_revised_provider_failure_preserves_ledger_and_hides_sensitive_error_body(tmp_path):
    provider = Provider()
    secret = "DO_NOT_PERSIST_PROVIDER_SECRET_OR_PRIVATE_PATH"
    with workbench(tmp_path, provider) as (client, _):
        _, original = create_approved(client)
        changed = edit(client, original).json()
        provider.mutate = lambda *args: httpx.Response(401, text=secret)
        response = review(client, changed)
        assert response.status_code == 202, response.text
        run = wait_run(client, response.json()["id"])
        assert run["status"] == "failed"
        assert run["usage"]["request_count"] == 1
        assert run["usage"]["reserved_output_tokens"] == 256
        assert run["usage"]["total_tokens"] is None
        result = wait_revision(client, changed, "needs_changes")
        assert secret not in json.dumps(run)
        assert secret not in json.dumps(result)
        assert "not-a-real-key" not in json.dumps(result)
        assert download(client, result).status_code == 409
        assert len(provider.calls) == 7
