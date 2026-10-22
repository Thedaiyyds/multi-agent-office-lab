"""Local-only report API with explicit, bounded background agent execution."""

import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from office_agents.config import ConfigurationError, Settings
from office_agents.workbench.delivery import create_delivery_router
from office_agents.workbench.demo import (
    create_demo_router,
    create_local_data_router,
    load_local_dataset,
)
from office_agents.workbench.execution import create_execution_router
from office_agents.workbench.materials import create_material_router
from office_agents.workbench.statistics import create_statistics_router
from office_agents.workbench.tasks import create_task_router

VERSION = "2.4.1"
Workspace = Literal["normal", "demo"]
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "testserver"}


class DraftInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=160)
    department: str = Field(min_length=1, max_length=80)
    start_date: date
    end_date: date
    focus: str = Field(default="", max_length=4000)
    sections: list[str] = Field(min_length=1, max_length=20)

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def date_only(cls, value):
        if not isinstance(value, str) or len(value) != 10:
            raise ValueError("日期须为 YYYY-MM-DD")
        try:
            if date.fromisoformat(value).isoformat() != value:
                raise ValueError
        except ValueError:
            raise ValueError("日期须为有效的 YYYY-MM-DD") from None
        return value

    @field_validator("sections")
    @classmethod
    def clean_sections(cls, value: list[str]) -> list[str]:
        cleaned = [section.strip() for section in value]
        if any(not section or len(section) > 100 for section in cleaned):
            raise ValueError("章节须为 1 至 100 字的非空文字")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("章节名称不能重复")
        return cleaned

    @model_validator(mode="after")
    def valid_period(self):
        if self.end_date <= self.start_date:
            raise ValueError("结束日必须晚于开始日，统计不包含结束日")
        return self


class DraftUpdate(DraftInput):
    expected_version: int = Field(ge=1, strict=True)


class Report(DraftInput):
    id: str
    workspace: Workspace
    version: int
    status: Literal["draft", "pending_review", "needs_changes", "approved"]
    created_at: str
    updated_at: str


class ReportList(BaseModel):
    items: list[Report]


class Health(BaseModel):
    status: Literal["ok"] = "ok"
    version: str = VERSION


class SystemInfo(BaseModel):
    version: str = VERSION
    model_configured: bool
    capabilities: list[str] = [
        "drafts",
        "workspace_isolation",
        "materials",
        "demo_materials",
        "statistics",
        "agent_execution",
        "local_data_sources",
        "report_revisions",
        "markdown_pdf_delivery",
    ]


def create_app(
    database_path: str | Path | None = None,
    static_dir: str | Path | Literal[False] | None = None,
    demo_root: str | Path | None = None,
    execution_options: dict | None = None,
    delivery_options: dict | None = None,
    local_data_root: str | Path | None = None,
):
    """Build an isolated app; callers can choose a temporary database in tests."""
    project_root = Path(__file__).resolve().parents[3]
    data_dir = Path(os.getenv("WORKBENCH_DATA_DIR", project_root / "outputs/workbench"))
    database = Path(database_path or data_dir / "workbench.sqlite3").resolve()
    database.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connection():
        db = sqlite3.connect(database, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    with connection() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS reports (
                id TEXT PRIMARY KEY,
                workspace TEXT NOT NULL CHECK(workspace IN ('normal', 'demo')),
                title TEXT NOT NULL,
                department TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                focus TEXT NOT NULL,
                sections TEXT NOT NULL,
                version INTEGER NOT NULL CHECK(version > 0),
                status TEXT NOT NULL CHECK(status = 'draft'),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS reports_workspace_updated
                ON reports(workspace, updated_at DESC);
            CREATE TABLE IF NOT EXISTS report_creation_keys (
                workspace TEXT NOT NULL,
                key TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                response TEXT NOT NULL,
                PRIMARY KEY(workspace, key)
            );
        """)
    database.chmod(0o600)

    app = FastAPI(title="汇报协作工作台 API", version=VERSION)
    demo_root = Path(demo_root or project_root / "data/demo").resolve()
    local_data_root = Path(local_data_root or project_root / "data/office-cases").resolve()
    material_router = create_material_router(connection, database.parent / "materials", demo_root)
    app.include_router(material_router)
    app.include_router(create_demo_router(material_router.material_service, connection, demo_root))
    app.include_router(create_local_data_router(material_router.material_service, local_data_root))
    app.include_router(create_statistics_router(connection, material_router.material_service))
    options = {
        "local_provider": lambda kind: load_local_dataset(
            local_data_root, kind, include_notes=True
        ),
        **(execution_options or {}),
    }
    execution_router = create_execution_router(
        connection, material_router.material_service, **options
    )
    app.include_router(execution_router)
    app.state.execution_service = execution_router.execution_service
    delivery_router = create_delivery_router(
        connection,
        execution_router.execution_service,
        database.parent / "reports",
        **(delivery_options or {}),
    )
    app.include_router(delivery_router)
    delivery_service = delivery_router.delivery_service
    app.state.delivery_service = delivery_service
    app.include_router(create_task_router(connection, delivery_service))

    @app.middleware("http")
    async def local_requests_only(request: Request, call_next):
        try:
            host = urlsplit("http://" + request.headers.get("host", ""))
            host_valid = (
                host.hostname in LOCAL_HOSTS
                and host.username is None
                and host.password is None
                and not host.path
                and not host.query
                and not host.fragment
            )
            host_port = host.port or 80
        except ValueError:
            host_valid = False
        if not host_valid:
            return JSONResponse({"detail": "仅允许本机访问"}, status_code=403)
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse({"detail": "拒绝跨站写入"}, status_code=403)
            if origin:
                try:
                    parsed = urlsplit(origin)
                    origin_valid = (
                        parsed.scheme == "http"
                        and parsed.hostname in LOCAL_HOSTS
                        and parsed.username is None
                        and parsed.password is None
                        and not parsed.path
                        and not parsed.query
                        and not parsed.fragment
                        and (parsed.port or 80) in {host_port, 5173}
                    )
                except ValueError:
                    origin_valid = False
                if not origin_valid:
                    return JSONResponse({"detail": "拒绝非本机来源写入"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Cache-Control"] = "no-store"
        return response

    def row_report(row: sqlite3.Row, db) -> dict:
        result = dict(row)
        result["sections"] = json.loads(result["sections"])
        result["status"] = delivery_service.report_status(result["id"], result["workspace"], db=db)
        return result

    def find_report(db, report_id: str, workspace: Workspace) -> dict:
        row = db.execute(
            "SELECT * FROM reports WHERE id = ? AND workspace = ?", (report_id, workspace)
        ).fetchone()
        if row is None:
            raise HTTPException(404, "未找到该工作区中的报告")
        return row_report(row, db)

    @app.get("/api/v1/health", response_model=Health)
    def health():
        return Health()

    @app.get("/api/v1/system", response_model=SystemInfo)
    def system_info():
        try:
            settings = Settings.from_env()
            settings.validate_for_live()
            configured = bool(settings.api_key)
        except (ConfigurationError, ValueError):
            configured = False
        return SystemInfo(model_configured=configured)

    @app.get("/api/v1/reports", response_model=ReportList)
    def list_reports(
        x_workspace: Annotated[Workspace, Header()] = "normal",
        search: Annotated[str, Query(max_length=200)] = "",
        status: Literal["", "draft", "pending_review", "needs_changes", "approved"] | None = None,
    ):
        status = status or None
        with connection() as db:
            rows = db.execute(
                """SELECT * FROM reports WHERE workspace = ?
                    AND instr(lower(title || char(10) || department), lower(?)) > 0
                    ORDER BY updated_at DESC, id DESC""",
                (x_workspace, search.strip()),
            ).fetchall()
            reports = [row_report(row, db) for row in rows]
        return {"items": [report for report in reports if not status or report["status"] == status]}

    @app.post("/api/v1/reports", response_model=Report, status_code=201)
    def create_report(
        draft: DraftInput,
        x_workspace: Annotated[Workspace, Header()] = "normal",
        idempotency_key: Annotated[str | None, Header(min_length=1, max_length=128)] = None,
    ):
        values = draft.model_dump(mode="json")
        canonical = json.dumps(values, ensure_ascii=False, sort_keys=True)
        digest = hashlib.sha256(canonical.encode()).hexdigest()
        with connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if idempotency_key is not None:
                saved = db.execute(
                    "SELECT * FROM report_creation_keys WHERE workspace = ? AND key = ?",
                    (x_workspace, idempotency_key),
                ).fetchone()
                if saved:
                    if saved["request_hash"] != digest:
                        raise HTTPException(409, "该防重标识已用于不同的报告内容")
                    return json.loads(saved["response"])
            now = datetime.now(UTC).isoformat()
            report = {
                **values,
                "id": str(uuid4()),
                "workspace": x_workspace,
                "version": 1,
                "status": "draft",
                "created_at": now,
                "updated_at": now,
            }
            db.execute(
                """INSERT INTO reports VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    report["id"],
                    x_workspace,
                    draft.title,
                    draft.department,
                    values["start_date"],
                    values["end_date"],
                    draft.focus,
                    json.dumps(draft.sections, ensure_ascii=False),
                    1,
                    "draft",
                    now,
                    now,
                ),
            )
            if idempotency_key is not None:
                db.execute(
                    "INSERT INTO report_creation_keys VALUES (?, ?, ?, ?)",
                    (x_workspace, idempotency_key, digest, json.dumps(report, ensure_ascii=False)),
                )
            return report

    @app.get("/api/v1/reports/{report_id}", response_model=Report)
    def get_report(report_id: str, x_workspace: Annotated[Workspace, Header()] = "normal"):
        with connection() as db:
            return find_report(db, report_id, x_workspace)

    @app.patch("/api/v1/reports/{report_id}/draft", response_model=Report)
    def update_report(
        report_id: str,
        draft: DraftUpdate,
        x_workspace: Annotated[Workspace, Header()] = "normal",
    ):
        with connection() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = find_report(db, report_id, x_workspace)
            if existing["version"] != draft.expected_version:
                raise HTTPException(409, "报告已被其他页面修改，请刷新后再保存")
            db.execute(
                """UPDATE reports SET title = ?, department = ?, start_date = ?, end_date = ?,
                    focus = ?, sections = ?, version = version + 1, updated_at = ?
                    WHERE id = ? AND workspace = ? AND version = ?""",
                (
                    draft.title,
                    draft.department,
                    draft.start_date.isoformat(),
                    draft.end_date.isoformat(),
                    draft.focus,
                    json.dumps(draft.sections, ensure_ascii=False),
                    datetime.now(UTC).isoformat(),
                    report_id,
                    x_workspace,
                    draft.expected_version,
                ),
            )
            return find_report(db, report_id, x_workspace)

    if static_dir is False:
        return app
    static_root = Path(static_dir or project_root / "frontend/dist").resolve()

    @app.get("/{asset_path:path}", include_in_schema=False)
    def frontend(asset_path: str):
        if asset_path == "api" or asset_path.startswith("api/"):
            raise HTTPException(404, "接口不存在")
        candidate = (static_root / asset_path).resolve()
        if not candidate.is_relative_to(static_root) or any(
            part.startswith(".") for part in Path(asset_path).parts
        ):
            raise HTTPException(404, "文件不存在")
        if candidate.is_file():
            return FileResponse(candidate)
        if Path(asset_path).suffix or asset_path.startswith("assets/"):
            raise HTTPException(404, "文件不存在")
        index = static_root / "index.html"
        if not index.is_file():
            raise HTTPException(404, "请先构建前端页面")
        return FileResponse(index)

    return app
