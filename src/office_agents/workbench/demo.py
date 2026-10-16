"""Explicit local demo sources, read only and unavailable to normal workspaces."""

import csv
import hashlib
import io
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict

from office_agents.workbench.materials import MaterialService

Workspace = Literal["normal", "demo"]
DatasetKind = Literal["projects", "attendance", "achievements", "satisfaction"]
CASE_FILES = (
    ("项目进度.csv", "projects"),
    ("人员考勤.csv", "attendance"),
    ("成果统计.csv", "achievements"),
    ("工作说明.txt", "notes"),
    ("季度工作记录.docx", "notes"),
)
PROVIDER_FILES = {
    "projects": ("technical-q2", "项目进度.csv"),
    "attendance": ("technical-q2", "人员考勤.csv"),
    "achievements": ("technical-q2", "成果统计.csv"),
    "satisfaction": ("administration-q1", "满意度.csv"),
}


class DemoImport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: DatasetKind


def require_demo(workspace):
    if workspace != "demo":
        raise HTTPException(403, "模拟案例和接口仅在演示空间开放，请先进入独立演示空间")


def create_demo_router(service: MaterialService, connection, demo_root: Path):
    router = APIRouter()

    def source_file(folder, name):
        path = (demo_root / folder / name).resolve()
        if not path.is_relative_to(demo_root) or not path.is_file():
            raise HTTPException(503, "演示材料尚未就绪，请检查 data/demo 样例文件")
        return path

    def provider(kind):
        folder, filename = PROVIDER_FILES[kind]
        data = source_file(folder, filename).read_bytes()
        records = list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))
        if not records:
            raise HTTPException(503, "模拟接口没有可用记录，请检查 data/demo 样例文件")
        return {
            "dataset_id": f"{folder}:{kind}:" + hashlib.sha256(data).hexdigest()[:16],
            "source": "local_demo_api",
            "records": records,
        }

    @router.get("/api/v1/demo/catalog")
    def catalog(x_workspace: Annotated[Workspace, Header()] = "normal"):
        require_demo(x_workspace)
        return {
            "case": "technical-q2",
            "title": "技术部2026年第二季度工作汇报材料",
            "request": (
                "生成2026年第二季度技术部工作汇报，包含项目进度、人员考勤、成果统计，"
                "格式为Markdown，导出为PDF。"
            ),
            "files": [{"name": name, "kind": kind} for name, kind in CASE_FILES],
        }

    @router.get("/api/v1/demo/provider/{kind}")
    def local_provider(kind: DatasetKind, x_workspace: Annotated[Workspace, Header()] = "normal"):
        require_demo(x_workspace)
        return provider(kind)

    @router.post("/api/v1/materials/from-demo-api", status_code=201)
    def import_provider(
        payload: DemoImport, x_workspace: Annotated[Workspace, Header()] = "normal"
    ):
        require_demo(x_workspace)
        snapshot = provider(payload.kind)
        # Freeze the interface response as an immutable CSV, not a live URL reference.
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=list(snapshot["records"][0]))
        writer.writeheader()
        writer.writerows(snapshot["records"])
        draft = service.stage_import(
            stream.getvalue().encode("utf-8"),
            f"模拟接口_{payload.kind}.csv",
            payload.kind,
            x_workspace,
            source="local_api",
        )
        return {**draft, "dataset_id": snapshot["dataset_id"]}

    @router.post("/api/v1/demo/load")
    def load_case(x_workspace: Annotated[Workspace, Header()] = "normal"):
        require_demo(x_workspace)
        # Read, parse and validate every source before starting confirmations.
        sources = [
            (name, kind, source_file("technical-q2", name).read_bytes())
            for name, kind in CASE_FILES
        ]
        with connection() as db:
            before = {
                row[0]
                for row in db.execute("SELECT id FROM material_versions WHERE workspace = 'demo'")
            }
        staged = [
            service.stage_import(
                data,
                name,
                kind,
                "demo",
                source="demo",
                department="技术部",
                start_date="2026-04-01",
                end_date="2026-07-01",
            )
            for name, kind, data in sources
        ]
        issues = [
            issue
            for draft in staged
            for issue in service.validate_import(
                draft["id"], "demo", {"mapping": draft["suggested_mapping"]}
            )
            if issue["severity"] == "error"
        ]
        if issues:
            raise HTTPException(
                422, {"message": "演示案例未通过校验，尚未确认任何材料", "issues": issues[:201]}
            )
        materials = [
            service.confirm(
                draft["id"],
                "demo",
                {
                    "mapping": draft["suggested_mapping"],
                },
            )
            for draft in staged
        ]
        return {
            "case": "technical-q2",
            "materials": materials,
            "already_loaded": all(item["id"] in before for item in materials),
        }

    return router
