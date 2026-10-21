"""One task per report, with lightweight history and reversible list housekeeping."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool

ACTIVE = {"queued", "running", "awaiting_confirmation"}


def run_summaries(db, workspace, report_id=None):
    rows = db.execute(
        """SELECT id,report_id,status,
        json_extract(payload,'$.mode') AS mode,
        json_extract(payload,'$.created_at') AS created_at,
        json_extract(payload,'$.updated_at') AS updated_at,
        json_extract(payload,'$.report_version') AS report_version,
        json_extract(payload,'$.user_text') AS user_text,
        json_extract(payload,'$.material_ids') AS material_ids,
        json_extract(payload,'$.requirements') AS requirements,
        json_extract(payload,'$.request.planning_only') AS planning,
        json_extract(payload,'$.material_profile.scopes') AS scopes
        FROM execution_runs WHERE workspace=? AND (? IS NULL OR report_id=?) ORDER BY rowid DESC""",
        (workspace, report_id, report_id),
    ).fetchall()
    return [
        dict(
            id=row["id"],
            report_id=row["report_id"],
            status=row["status"],
            mode=row["mode"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            report_version=row["report_version"],
            user_text=row["user_text"],
            material_ids=json.loads(row["material_ids"] or "[]"),
            requirements=json.loads(row["requirements"]) if row["requirements"] else None,
            request=dict(planning_only=bool(row["planning"])),
            scopes=json.loads(row["scopes"] or "[]"),
        )
        for row in rows
    ]


class VisibilityInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ids: list[str] = Field(min_length=1, max_length=100)
    hidden: StrictBool


def create_task_router(connection, delivery):
    router = APIRouter()
    with connection() as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS task_hidden (workspace TEXT NOT NULL,"
            "task_id TEXT NOT NULL,hidden_at TEXT NOT NULL,PRIMARY KEY(workspace,task_id))"
        )

    def listing(workspace, db):
        runs = run_summaries(db, workspace)
        by_report, unbound = {}, {}
        for run in runs:
            if run["report_id"]:
                by_report.setdefault(run["report_id"], []).append(run)
            else:
                identity = json.dumps(
                    [
                        run["user_text"].strip(),
                        sorted(run["material_ids"]),
                        run["mode"],
                        run["request"]["planning_only"],
                    ],
                    ensure_ascii=False,
                )
                key = "attempt:" + hashlib.sha256(identity.encode()).hexdigest()
                unbound.setdefault(key, []).append(run)
        hidden = {
            row["task_id"]: row["hidden_at"]
            for row in db.execute("SELECT * FROM task_hidden WHERE workspace=?", (workspace,))
        }
        items, attempts = [], []
        for report in db.execute(
            "SELECT * FROM reports WHERE workspace=?", (workspace,)
        ).fetchall():
            history = sorted(
                by_report.get(report["id"], []), key=lambda run: run["updated_at"], reverse=True
            )
            latest = history[0] if history else None
            business = delivery.report_status(report["id"], workspace, db=db)
            status = {"approved": "completed"}.get(business, business)
            if (
                latest
                and latest["report_version"] == report["version"]
                and latest["status"] == "completed"
                and business == "draft"
            ):
                status = "completed"
            if (
                latest
                and latest["report_version"] == report["version"]
                and latest["status"] != "completed"
            ):
                status = latest["status"]
            updated = max(report["updated_at"], latest["updated_at"] if latest else "")
            task_id = "report:" + report["id"]
            items.append(
                dict(
                    id=task_id,
                    title=report["title"],
                    department=report["department"],
                    start_date=report["start_date"],
                    end_date=report["end_date"],
                    updated_at=updated,
                    status=status,
                    mode=latest["mode"] if latest else None,
                    report_id=report["id"],
                    run_count=len(history),
                    has_report=business != "draft",
                    href=f"/runs/{latest['id']}"
                    if latest
                    and (
                        status not in {"completed", "draft", "pending_review", "needs_changes"}
                        or status == "completed"
                        and business == "draft"
                    )
                    else f"/reports/{report['id']}",
                    hidden=bool(hidden.get(task_id, "") >= updated and status not in ACTIVE),
                    attempts=[],
                )
            )
        for key, history in unbound.items():
            active = [run for run in history if run["status"] in ACTIVE]
            latest = max(active or history, key=lambda run: run["updated_at"])
            req = latest["requirements"] or {}
            task = dict(
                id=key,
                title=req.get("title") or latest["user_text"][:120],
                department=req.get("department") or "待确定范围",
                start_date=req.get("start_date", ""),
                end_date=req.get("end_date", ""),
                updated_at=latest["updated_at"],
                status=latest["status"],
                mode=latest["mode"],
                report_id=None,
                has_report=False,
                run_count=len(history),
                href="/runs/" + latest["id"],
                hidden=bool(hidden.get(key, "") >= latest["updated_at"] and not active),
                attempts=[
                    dict(id=run["id"], status=run["status"], created_at=run["created_at"])
                    for run in history
                ],
            )
            (items if active else attempts).append(task)
        return dict(
            items=sorted(items, key=lambda item: item["updated_at"], reverse=True),
            attempts=sorted(attempts, key=lambda item: item["updated_at"], reverse=True),
        )

    @router.get("/api/v1/tasks")
    def tasks(x_workspace: Annotated[Literal["normal", "demo"], Header()] = "normal"):
        with connection() as db:
            return listing(x_workspace, db)

    @router.post("/api/v1/tasks/visibility")
    def visibility(
        request: VisibilityInput,
        x_workspace: Annotated[Literal["normal", "demo"], Header()] = "normal",
    ):
        with connection() as db:
            db.execute("BEGIN IMMEDIATE")
            current = listing(x_workspace, db)
            tasks = {task["id"]: task for task in current["items"] + current["attempts"]}
            for task_id in request.ids:
                if task_id not in tasks:
                    raise HTTPException(404, "未找到该工作区的任务")
                if request.hidden and tasks[task_id]["status"] in ACTIVE:
                    raise HTTPException(409, "正在处理或等待确认的任务不能收起")
            for task_id in set(request.ids):
                if request.hidden:
                    db.execute(
                        "INSERT OR REPLACE INTO task_hidden VALUES(?,?,?)",
                        (x_workspace, task_id, datetime.now(UTC).isoformat()),
                    )
                else:
                    db.execute(
                        "DELETE FROM task_hidden WHERE workspace=? AND task_id=?",
                        (x_workspace, task_id),
                    )
        return dict(updated=len(set(request.ids)))

    return router
