"""Immutable reviewed report revisions and local-only Markdown/PDF delivery."""

import hashlib
import json
import threading
from contextlib import asynccontextmanager, nullcontext
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import Field

from office_agents.workbench.execution import (
    TERMINAL,
    Contract,
    Narrative,
    render_markdown,
    validate_narrative,
)
from office_agents.workbench.materials import canonical_json

Workspace = Literal["normal", "demo"]
Format = Literal["md", "pdf"]
SNAPSHOT_FIELDS = (
    "workspace",
    "report_id",
    "report_version",
    "mode",
    "requirements",
    "outline",
    "statistics",
    "facts",
    "notes",
    "narrative",
    "draft_markdown",
    "material_ids",
    "materials",
    "source_datasets",
    "user_text",
)


class RevisionInput(Contract):
    expected_report_version: int = Field(ge=1, strict=True)
    expected_revision_id: str = Field(min_length=1, max_length=128)
    narrative: Narrative


class ReviewInput(Contract):
    request_budget: int = Field(default=2, ge=1, le=2, strict=True)
    output_budget: int = Field(default=512, ge=1, le=512, strict=True)


def _now():
    return datetime.now(UTC).isoformat()


def _digest(value):
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _file_digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _approved(run):
    return (
        run["status"] == "completed"
        and bool((run.get("review") or {}).get("passed"))
        and bool((run.get("review") or {}).get("program_passed"))
        and bool((run.get("review") or {}).get("model_passed"))
        and bool((run.get("acceptance") or {}).get("accepted"))
        and not validate_narrative(run)
    )


class DeliveryService:
    def __init__(self, connection, execution_service, root, *, render_pdf=None):
        self.connection = connection
        self.execution_service = execution_service
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.render_pdf = render_pdf
        # ponytail: one local export lock; per-report locks only if local rendering is a bottleneck.
        self._export_lock = threading.RLock()
        with connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS report_revisions (
                    id TEXT PRIMARY KEY, workspace TEXT NOT NULL,
                    report_id TEXT NOT NULL, report_version INTEGER NOT NULL,
                    number INTEGER NOT NULL, source_run_id TEXT UNIQUE,
                    content_hash TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL,
                    UNIQUE(workspace,report_id,number)
                );
                CREATE TABLE IF NOT EXISTS report_artifacts (
                    workspace TEXT NOT NULL, revision_id TEXT NOT NULL,
                    format TEXT NOT NULL, state TEXT NOT NULL,
                    snapshot_hash TEXT NOT NULL, file_sha256 TEXT, byte_size INTEGER,
                    relative_path TEXT, error TEXT,
                    PRIMARY KEY(workspace,revision_id,format)
                );
                CREATE INDEX IF NOT EXISTS delivery_report
                    ON report_revisions(workspace,report_id,number DESC);
            """)

    @staticmethod
    def _save(db, revision):
        revision["updated_at"] = _now()
        db.execute(
            "UPDATE report_revisions SET status=?,payload=? WHERE id=?",
            (revision["status"], canonical_json(revision), revision["id"]),
        )

    @staticmethod
    def _report(db, report_id, workspace):
        report = db.execute(
            "SELECT version FROM reports WHERE id=? AND workspace=?", (report_id, workspace)
        ).fetchone()
        if report is None:
            raise HTTPException(404, "未找到该工作区中的报告")
        return report[0]

    def _read(self, db, report_id, revision_id, workspace):
        self._report(db, report_id, workspace)
        row = db.execute(
            "SELECT * FROM report_revisions WHERE id=? AND report_id=? AND workspace=?",
            (revision_id, report_id, workspace),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "未找到该工作区中的报告修订")
        return self._decode(row)

    @staticmethod
    def _decode(row):
        revision = json.loads(row["payload"])
        if any(
            revision[key] != row[key]
            for key in (
                "id",
                "workspace",
                "report_id",
                "report_version",
                "number",
                "content_hash",
                "status",
            )
        ) or revision["content_hash"] != _digest(revision["snapshot"]):
            raise HTTPException(409, "报告快照校验失败，不能审核或导出")
        return revision

    def _current(self, db, revision):
        version = self._report(db, revision["report_id"], revision["workspace"])
        latest = db.execute(
            "SELECT id FROM report_revisions WHERE workspace=? AND report_id=? "
            "ORDER BY number DESC LIMIT 1",
            (revision["workspace"], revision["report_id"]),
        ).fetchone()
        return version == revision["report_version"] and latest[0] == revision["id"]

    @staticmethod
    def _summary(revision):
        return {
            key: revision[key]
            for key in (
                "id",
                "workspace",
                "report_id",
                "report_version",
                "number",
                "source_run_id",
                "content_hash",
                "status",
                "mode",
                "created_at",
                "updated_at",
                "review_run_id",
                "review",
                "acceptance",
                "review_error",
            )
        }

    def _public(self, db, revision, *, detail):
        result = self._summary(revision)
        result["current"] = self._current(db, revision)
        result["artifacts"] = self._artifacts(db, revision)
        if detail:
            result.update(
                snapshot=revision["snapshot"], review_attempts=revision["review_attempts"]
            )
        return result

    @staticmethod
    def _artifacts(db, revision):
        rows = db.execute(
            "SELECT format,state,snapshot_hash,file_sha256,byte_size,error "
            "FROM report_artifacts WHERE revision_id=? AND workspace=? ORDER BY format",
            (revision["id"], revision["workspace"]),
        ).fetchall()
        found = {row["format"]: dict(row) for row in rows}
        return [
            found.get(
                fmt,
                dict(
                    format=fmt,
                    state="missing",
                    snapshot_hash=revision["content_hash"],
                    file_sha256=None,
                    byte_size=None,
                    error=None,
                ),
            )
            for fmt in ("md", "pdf")
        ]

    def report_status(self, report_id, workspace, *, db=None):
        """Derive UI status without migrating the historical draft-only reports table."""
        with nullcontext(db) if db is not None else self.connection() as current_db:
            version = self._report(current_db, report_id, workspace)
            row = current_db.execute(
                "SELECT * FROM report_revisions "
                "WHERE report_id=? AND workspace=? ORDER BY number DESC LIMIT 1",
                (report_id, workspace),
            ).fetchone()
        if row is None:
            return "draft"
        revision = self._decode(row)
        if revision["report_version"] != version:
            return "draft"
        return {
            "approved": "approved",
            "needs_changes": "needs_changes",
            "needs_review": "pending_review",
            "reviewing": "pending_review",
        }.get(revision["status"], "draft")

    @staticmethod
    def _require_approval(revision):
        receipt = revision["review_attempts"][-1] if revision["review_attempts"] else {}
        review = receipt.get("review") or {}
        acceptance = receipt.get("acceptance") or {}
        if not (
            revision["status"] == "approved"
            and receipt.get("content_hash") == revision["content_hash"]
            and receipt.get("status") == "completed"
            and all(review.get(key) for key in ("passed", "program_passed", "model_passed"))
            and acceptance.get("accepted")
        ):
            raise HTTPException(409, "该修订尚未通过Checker与Manager审核，不能导出合格报告")

    def list(self, report_id, workspace):
        with self.connection() as db:
            report_version = self._report(db, report_id, workspace)
            rows = db.execute(
                "SELECT * FROM report_revisions WHERE report_id=? AND workspace=? "
                "ORDER BY number DESC",
                (report_id, workspace),
            ).fetchall()
            revisions = [self._decode(row) for row in rows]
            items = [self._public(db, revision, detail=False) for revision in revisions]
        return dict(
            current_revision_id=next((item["id"] for item in items if item["current"]), None),
            report_version=report_version,
            items=items,
        )

    def get(self, report_id, revision_id, workspace):
        with self.connection() as db:
            revision = self._read(db, report_id, revision_id, workspace)
            return self._public(db, revision, detail=True)

    @staticmethod
    def _insert(db, run, *, source_run_id, status):
        revision_id, now = uuid4().hex, _now()
        number = db.execute(
            "SELECT coalesce(max(number),0)+1 FROM report_revisions "
            "WHERE report_id=? AND workspace=?",
            (run["report_id"], run["workspace"]),
        ).fetchone()[0]
        snapshot = {key: deepcopy(run[key]) for key in SNAPSHOT_FIELDS}
        snapshot["revision_id"] = revision_id
        snapshot["number"] = number
        snapshot["markdown"] = snapshot.pop("draft_markdown")
        revision = dict(
            id=revision_id,
            workspace=run["workspace"],
            report_id=run["report_id"],
            report_version=run["report_version"],
            number=number,
            source_run_id=source_run_id,
            content_hash=_digest(snapshot),
            status=status,
            mode=run["mode"],
            snapshot=snapshot,
            created_at=now,
            updated_at=now,
            review_run_id=None,
            review=deepcopy(run.get("review")) if status == "approved" else None,
            acceptance=deepcopy(run.get("acceptance")) if status == "approved" else None,
            review_error=None,
            review_attempts=[],
        )
        if status == "approved":
            revision["review_attempts"].append(
                dict(
                    run_id=run["id"],
                    content_hash=revision["content_hash"],
                    status=run["status"],
                    review=run["review"],
                    acceptance=run["acceptance"],
                    usage=run["usage"],
                    created_at=now,
                )
            )
        db.execute(
            "INSERT INTO report_revisions VALUES(?,?,?,?,?,?,?,?,?)",
            (
                revision_id,
                run["workspace"],
                run["report_id"],
                run["report_version"],
                number,
                source_run_id,
                revision["content_hash"],
                status,
                canonical_json(revision),
            ),
        )
        return revision

    def record_run(self, run):
        """Terminal callback; idempotent initial capture and revision-review receipts."""
        if run.get("run_type") == "revision_review":
            return self._record_review(run)
        if not _approved(run):
            return None
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._report(db, run["report_id"], run["workspace"])
            row = db.execute(
                "SELECT payload FROM report_revisions WHERE source_run_id=?", (run["id"],)
            ).fetchone()
            revision = (
                json.loads(row[0])
                if row
                else self._insert(db, run, source_run_id=run["id"], status="approved")
            )
        self.ensure_exports(run["report_id"], revision["id"], run["workspace"])
        return revision["id"]

    def edit(self, report_id, workspace, request):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            version = self._report(db, report_id, workspace)
            if version != request.expected_report_version:
                raise HTTPException(409, "报告需求已变更，请刷新后重试")
            base = self._read(db, report_id, request.expected_revision_id, workspace)
            if not self._current(db, base):
                raise HTTPException(409, "报告修订已更新，请刷新后再编辑")
            if base["status"] == "reviewing":
                raise HTTPException(409, "该修订正在审核，请等待结束或取消后再编辑")
            run = self._frozen_run(base)
            run["narrative"] = request.narrative.model_dump()
            run["draft_markdown"] = render_markdown(run, run["narrative"])
            issues = validate_narrative(run)
            if issues:
                raise HTTPException(422, dict(message="叙述校验失败", issues=issues))
            if run["narrative"] == base["snapshot"]["narrative"]:
                raise HTTPException(422, "叙述没有变化，无需建立新修订")
            revision = self._insert(db, run, source_run_id=None, status="needs_review")
            return self._public(db, revision, detail=True)

    def _frozen_run(self, revision):
        snapshot = revision["snapshot"]
        run = {key: deepcopy(snapshot[key]) for key in SNAPSHOT_FIELDS if key != "draft_markdown"}
        run["draft_markdown"] = snapshot["markdown"]
        run["request"] = dict(max_revisions=0)
        return run

    def review(self, report_id, revision_id, workspace, request, key):
        with self.connection() as db:
            revision = self._read(db, report_id, revision_id, workspace)
        frozen = self._frozen_run(revision)

        def on_submit(db, run):
            current = self._read(db, report_id, revision_id, workspace)
            if not self._current(db, current):
                raise HTTPException(409, "只能审核当前修订；历史合格版仍可下载")
            if current["status"] not in {"needs_review", "needs_changes"}:
                raise HTTPException(409, "该修订已在审核中或已经合格")
            issues = validate_narrative(frozen)
            if issues:
                raise HTTPException(422, dict(message="叙述校验失败", issues=issues))
            current.update(status="reviewing", review_run_id=run["id"], review_error=None)
            self._save(db, current)

        return self.execution_service.submit_review(
            frozen,
            revision_id,
            revision["content_hash"],
            key,
            request_budget=request.request_budget,
            output_budget=request.output_budget,
            on_submit=on_submit,
        )

    def _record_review(self, run):
        if run["status"] not in TERMINAL:
            return None
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            revision = self._read(
                db, run["report_id"], run["delivery_revision_id"], run["workspace"]
            )
            if revision["content_hash"] != run["delivery_content_hash"]:
                raise HTTPException(409, "审核结果与报告快照不一致")
            if run["id"] in {item["run_id"] for item in revision["review_attempts"]}:
                return revision["id"]
            if revision["review_run_id"] != run["id"]:
                raise HTTPException(409, "审核结果已过期")
            approved = _approved(run)
            revision["review_attempts"].append(
                dict(
                    run_id=run["id"],
                    content_hash=revision["content_hash"],
                    status=run["status"],
                    review=run["review"],
                    acceptance=run["acceptance"],
                    usage=run["usage"],
                    created_at=_now(),
                )
            )
            revision.update(
                status="approved" if approved else "needs_changes",
                review=run["review"],
                acceptance=run["acceptance"],
                review_error=None
                if approved
                else (
                    run.get("error")
                    or dict(code=run["status"], message="审核未完成或未通过，请核对意见后重试")
                ),
            )
            self._save(db, revision)
        if approved:
            self.ensure_exports(run["report_id"], revision["id"], run["workspace"])
        return revision["id"]

    def reconcile(self):
        """Recover receipts and local exports; never submit or repeat a model call."""
        with self.connection() as db:
            rows = db.execute(
                "SELECT payload FROM execution_runs WHERE status NOT IN ('queued','running')"
            ).fetchall()
        for row in rows:
            try:
                self.record_run(json.loads(row[0]))
            except HTTPException:
                # Corrupt/missing snapshot is deliberately left blocked for inspection.
                continue
        with self.connection() as db:
            rows = db.execute(
                "SELECT payload FROM report_revisions WHERE status='approved'"
            ).fetchall()
        for row in rows:
            revision = json.loads(row[0])
            try:
                self.ensure_exports(revision["report_id"], revision["id"], revision["workspace"])
            except HTTPException:
                continue

    def _artifact(self, db, revision, fmt, state, **values):
        payload = dict(
            workspace=revision["workspace"],
            revision_id=revision["id"],
            format=fmt,
            state=state,
            snapshot_hash=revision["content_hash"],
            file_sha256=None,
            byte_size=None,
            relative_path=None,
            error=None,
        )
        payload.update(values)
        db.execute(
            "INSERT OR REPLACE INTO report_artifacts VALUES(?,?,?,?,?,?,?,?,?)",
            tuple(payload.values()),
        )

    def _file_path(self, revision, relative_path):
        if not isinstance(relative_path, str) or Path(relative_path).is_absolute():
            raise HTTPException(409, "导出文件定位校验失败，请重试导出")
        expected = (
            Path(revision["workspace"])
            / revision["report_id"]
            / revision["id"]
            / revision["content_hash"]
        )
        path = (self.root / relative_path).resolve()
        expected_root = (self.root / expected).resolve()
        if not path.is_relative_to(expected_root) or not expected_root.is_relative_to(self.root):
            raise HTTPException(409, "导出文件定位校验失败，请重试导出")
        return path

    def ensure_exports(self, report_id, revision_id, workspace):
        with self._export_lock:
            with self.connection() as db:
                revision = self._read(db, report_id, revision_id, workspace)
                self._require_approval(revision)
            relative_root = Path(workspace) / report_id / revision_id / revision["content_hash"]
            directory = self.root / relative_root
            try:
                directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            except OSError:
                with self.connection() as db:
                    for fmt in ("md", "pdf"):
                        self._artifact(
                            db,
                            revision,
                            fmt,
                            "failed",
                            error="本地文件导出失败，可重试；不会再次调用模型",
                        )
                return self.get(report_id, revision_id, workspace)
            for fmt in ("md", "pdf"):
                relative = str(relative_root / ("report." + fmt))
                destination = self._file_path(revision, relative)
                with self.connection() as db:
                    old = db.execute(
                        "SELECT * FROM report_artifacts WHERE workspace=? "
                        "AND revision_id=? AND format=?",
                        (workspace, revision_id, fmt),
                    ).fetchone()
                    if (
                        old is not None
                        and old["state"] == "ready"
                        and old["snapshot_hash"] == revision["content_hash"]
                        and old["relative_path"] == relative
                        and destination.is_file()
                        and _file_digest(destination) == old["file_sha256"]
                    ):
                        continue
                    self._artifact(db, revision, fmt, "running")
                temporary = directory / (uuid4().hex + "." + fmt)
                try:
                    if fmt == "md":
                        temporary.write_text(revision["snapshot"]["markdown"], encoding="utf-8")
                    else:
                        renderer = self.render_pdf
                        if renderer is None:
                            from office_agents.workbench.pdf_export import render_pdf

                            renderer = render_pdf
                        renderer(deepcopy(revision["snapshot"]), temporary)
                        if not temporary.is_file() or not temporary.read_bytes().startswith(
                            b"%PDF-"
                        ):
                            raise ValueError("Invalid local PDF output")
                    temporary.chmod(0o600)
                    temporary.replace(destination)
                    digest, size = _file_digest(destination), destination.stat().st_size
                    with self.connection() as db:
                        self._artifact(
                            db,
                            revision,
                            fmt,
                            "ready",
                            relative_path=relative,
                            file_sha256=digest,
                            byte_size=size,
                        )
                except Exception:
                    temporary.unlink(missing_ok=True)
                    with self.connection() as db:
                        self._artifact(
                            db,
                            revision,
                            fmt,
                            "failed",
                            error="本地文件导出失败，可重试；不会再次调用模型",
                        )
            return self.get(report_id, revision_id, workspace)

    def download(self, report_id, revision_id, workspace, fmt):
        with self.connection() as db:
            revision = self._read(db, report_id, revision_id, workspace)
            self._require_approval(revision)
            current = self._current(db, revision)
            row = db.execute(
                "SELECT * FROM report_artifacts WHERE workspace=? AND revision_id=? AND format=?",
                (workspace, revision_id, fmt),
            ).fetchone()
            if (
                row is None
                or row["state"] != "ready"
                or row["snapshot_hash"] != revision["content_hash"]
            ):
                raise HTTPException(409, "该格式尚未导出完成，请重试导出")
            path = self._file_path(revision, row["relative_path"])
            corrupt = not path.is_file() or _file_digest(path) != row["file_sha256"]
            if corrupt:
                self._artifact(db, revision, fmt, "failed", error="导出文件校验失败，请重试导出")
        # Commit the failed artifact before returning an HTTP error.
        if corrupt:
            raise HTTPException(409, "导出文件校验失败，请重试导出")
        return FileResponse(
            path,
            media_type="text/markdown; charset=utf-8" if fmt == "md" else "application/pdf",
            filename=f"report-r{revision['number']}.{fmt}",
            headers={
                "X-Report-Revision": revision_id,
                "X-Report-Snapshot": revision["content_hash"],
                "X-Artifact-SHA256": row["file_sha256"],
                "X-Report-Current": str(current).lower(),
            },
        )


def create_delivery_router(connection, execution_service, root, *, render_pdf=None):
    service = DeliveryService(connection, execution_service, root, render_pdf=render_pdf)
    execution_service.on_terminal = service.record_run

    @asynccontextmanager
    async def lifespan(app):
        service.reconcile()
        yield

    router = APIRouter(lifespan=lifespan)
    router.delivery_service = service

    @router.get("/api/v1/reports/{report_id}/revisions")
    def list_revisions(report_id: str, x_workspace: Annotated[Workspace, Header()] = "normal"):
        return service.list(report_id, x_workspace)

    @router.get("/api/v1/reports/{report_id}/revisions/{revision_id}")
    def get_revision(
        report_id: str, revision_id: str, x_workspace: Annotated[Workspace, Header()] = "normal"
    ):
        return service.get(report_id, revision_id, x_workspace)

    @router.post("/api/v1/reports/{report_id}/revisions", status_code=201)
    def edit_revision(
        report_id: str,
        request: RevisionInput,
        x_workspace: Annotated[Workspace, Header()] = "normal",
    ):
        return service.edit(report_id, x_workspace, request)

    @router.post("/api/v1/reports/{report_id}/revisions/{revision_id}/review", status_code=202)
    def review_revision(
        report_id: str,
        revision_id: str,
        request: ReviewInput,
        idempotency_key: Annotated[str, Header(min_length=1, max_length=128)],
        x_workspace: Annotated[Workspace, Header()] = "normal",
    ):
        return service.review(report_id, revision_id, x_workspace, request, idempotency_key)

    @router.get("/api/v1/reports/{report_id}/revisions/{revision_id}/exports")
    def list_exports(
        report_id: str, revision_id: str, x_workspace: Annotated[Workspace, Header()] = "normal"
    ):
        revision = service.get(report_id, revision_id, x_workspace)
        return {
            key: revision[key] for key in ("id", "content_hash", "current", "status", "artifacts")
        }

    @router.post("/api/v1/reports/{report_id}/revisions/{revision_id}/exports")
    def export_revision(
        report_id: str, revision_id: str, x_workspace: Annotated[Workspace, Header()] = "normal"
    ):
        return service.ensure_exports(report_id, revision_id, x_workspace)

    @router.get("/api/v1/reports/{report_id}/revisions/{revision_id}/exports/{fmt}")
    def download_revision(
        report_id: str,
        revision_id: str,
        fmt: Format,
        x_workspace: Annotated[Workspace, Header()] = "normal",
    ):
        return service.download(report_id, revision_id, x_workspace, fmt)

    return router
