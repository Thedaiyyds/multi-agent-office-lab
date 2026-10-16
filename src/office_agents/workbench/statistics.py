"""Deterministic, source-linked statistics over immutable confirmed materials."""

import json
import math
from datetime import UTC, date, datetime
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from office_agents.workbench.materials import canonical_json

POLICY_VERSION = "2026-10-v1"
Group = Literal["projects", "attendance", "achievements", "satisfaction"]
Workspace = Literal["normal", "demo"]
MAX_EXPECTED_PERSON_DAYS = 20_000


class StatisticsInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    expected_version: int = Field(ge=1, strict=True)
    material_ids: list[str] = Field(min_length=1, max_length=50)
    groups: list[Group] = Field(min_length=1, max_length=4)
    attendance_roster: list[str] = Field(default_factory=list, max_length=1000)
    attendance_dates: list[str] = Field(default_factory=list, max_length=3660)

    @field_validator("material_ids", "groups", "attendance_roster", "attendance_dates")
    @classmethod
    def distinct_values(cls, values):
        if any(not value.strip() or len(value) > 200 for value in values):
            raise ValueError("列表元素须为不超过 200 字的非空值")
        if len(values) != len(set(values)):
            raise ValueError("列表不能有重复值")
        return values

    @field_validator("attendance_dates")
    @classmethod
    def dates_only(cls, values):
        for value in values:
            try:
                if len(value) != 10 or date.fromisoformat(value).isoformat() != value:
                    raise ValueError
            except ValueError:
                raise ValueError("工作日期须为有效 YYYY-MM-DD") from None
        return values

    @model_validator(mode="after")
    def bounded_population(self):
        if bool(self.attendance_roster) != bool(self.attendance_dates):
            raise ValueError("考勤应到人员与工作日期须同时提供，或同时留空")
        if len(self.attendance_roster) * len(self.attendance_dates) > MAX_EXPECTED_PERSON_DAYS:
            raise ValueError("应到人员 × 工作日期最多 20000 个人日")
        return self


def _number(value):
    """Keep missing separate from real zero; reject non-finite or malformed input."""
    if value is None or str(value).strip() == "":
        return None
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("数值必须有限")
    return result


def _date(value):
    text = str(value)
    if len(text) != 10 or date.fromisoformat(text).isoformat() != text:
        raise ValueError("日期无效")
    return text


def _status(value):
    normalized = str(value).strip().lower().replace("-", "_")
    aliases = {
        "completed": {"completed", "complete", "done", "已完成", "完成", "已结项", "已验收"},
        "in_progress": {"in_progress", "in progress", "进行中", "进行", "开发中", "未完成", "在研"},
        "pending": {"pending", "not_started", "未开始", "待启动"},
        "paused": {"paused", "on_hold", "暂停", "已暂停"},
        "cancelled": {"cancelled", "canceled", "已取消", "取消"},
    }
    for status, words in aliases.items():
        if normalized in words:
            return status
    raise ValueError(f"无法识别项目状态：{value}")


def _unique_refs(records):
    result, seen = [], set()
    for record in records:
        for reference in record["refs"]:
            key = (reference["material_id"], reference["location"])
            if key not in seen:
                seen.add(key)
                result.append(reference)
    return result


def calculate_statistics(report, materials, groups, attendance_roster=None, attendance_dates=None):
    """Pure Data-Agent-ready calculator; materials are payload dictionaries plus full ``rows``.

    No model, file, database, or current-time access occurs here. Dates are half-open;
    structured row fields determine scope, while notes contribute no numeric claims.
    """
    department, start, end = report["department"], report["start_date"], report["end_date"]
    roster, work_dates = attendance_roster or [], attendance_dates or []
    if not department or _date(start) >= _date(end):
        raise ValueError("报告部门和起止期间无效")
    StatisticsInput(
        expected_version=1,
        material_ids=[material["id"] for material in materials],
        groups=groups,
        attendance_roster=roster,
        attendance_dates=work_dates,
    )
    if any(not start <= day < end for day in work_dates):
        raise ValueError("工作日期须位于报告期间内且不包含结束日")
    metrics, issues = [], []
    needs_input = False

    def add_issue(message, location="统计范围", severity="warning"):
        # A malformed large file must not create an unbounded error response.
        if len(issues) < 200:
            issues.append({"severity": severity, "location": location, "message": message})

    def metric(identifier, label, value, unit, definition, records, limitations=(), required=True):
        nonlocal needs_input
        if value is not None and (not isinstance(value, (int, float)) or not math.isfinite(value)):
            add_issue("汇总值超出有限数值范围，请缩小材料范围", severity="error")
            value = None
        if value is None and required:
            needs_input = True
        metrics.append(
            dict(
                id=identifier,
                label=label,
                value=value,
                unit=unit,
                definition=definition,
                source_refs=_unique_refs(records),
                limitations=list(limitations),
            )
        )

    def collect(kind):
        nonlocal needs_input
        matching = [material for material in materials if material["kind"] == kind]
        if not matching:
            add_issue(f"尚未选择{kind}分类材料")
            needs_input = True
        records = {}
        for material in matching:
            mapping = material["mapping"]
            for row in material["rows"]:
                location = f"{material['name']} / {row['location']}"
                values = {
                    key: str(row["values"].get(column, "")).strip()
                    for key, column in mapping.items()
                    if column
                }
                if values.get("department") != department:
                    continue
                try:
                    if kind == "projects":
                        effective = _date(values.get("effective_date", ""))
                        observed = _date(values.get("snapshot_date", ""))
                        if effective >= end or observed >= end:
                            continue
                        if observed < effective:
                            raise ValueError("项目快照早于生效日期")
                        identifier = values.get("project_id", "")
                        identity = (identifier, observed)
                        progress = _number(values.get("progress"))
                        if progress is None or not 0 <= progress <= 100:
                            raise ValueError("项目进度须为 0 至 100")
                        completed = values.get("completed_date", "")
                        if completed:
                            completed = _date(completed)
                            if completed < effective or completed > observed:
                                raise ValueError("完成日期须介于生效日和快照日之间")
                        canonical = dict(
                            project_id=identifier,
                            effective_date=effective,
                            snapshot_date=observed,
                            status=_status(values.get("status", "")),
                            progress=progress,
                            completed_date=completed,
                        )
                    else:
                        observed = _date(values.get("date", ""))
                        if not start <= observed < end:
                            continue
                        identifier_field = {
                            "attendance": "person_id",
                            "achievements": "achievement_id",
                            "satisfaction": "feedback_id",
                        }[kind]
                        identifier = values.get(identifier_field, "")
                        identity = (identifier, observed) if kind == "attendance" else (identifier,)
                        canonical = dict(values)
                        if kind == "attendance":
                            for field in (
                                "planned_hours",
                                "actual_hours",
                                "leave_hours",
                                "absent_hours",
                                "late_minutes",
                            ):
                                canonical[field] = _number(values.get(field))
                                if canonical[field] is not None and canonical[field] < 0:
                                    raise ValueError(f"{field} 不能为负数")
                        elif kind == "achievements":
                            canonical["project_id"] = values.get("project_id", "")
                        elif kind == "satisfaction":
                            for field in ("score", "scale_min", "scale_max"):
                                canonical[field] = _number(values.get(field))
                                if canonical[field] is None:
                                    raise ValueError("满意度分数和量表上下限不能为空")
                            if (
                                not canonical["scale_min"]
                                <= canonical["score"]
                                <= canonical["scale_max"]
                            ):
                                raise ValueError("满意度评分超出量表")
                            if canonical["scale_min"] >= canonical["scale_max"]:
                                raise ValueError("满意度量表上限须大于下限")
                            flag = values.get("valid", "").lower()
                            if flag not in {"", "true", "false", "1", "0"}:
                                raise ValueError("满意度有效标记无效")
                            canonical["valid"] = flag not in {"false", "0"}
                    if not identifier:
                        raise ValueError("业务编号不能为空")
                except (ValueError, TypeError, OverflowError) as error:
                    add_issue(str(error), location, "error")
                    continue
                reference = dict(
                    material_id=material["id"],
                    name=material["name"],
                    version=material["version"],
                    sha256=material["sha256"],
                    location=row["location"],
                    fields=list(dict.fromkeys(column for column in mapping.values() if column)),
                )
                if identity in records:
                    previous = records[identity]
                    if previous["values"] != canonical:
                        add_issue(
                            "同一业务记录存在冲突，不能选择其中一份覆盖：" + " / ".join(identity),
                            location,
                            "error",
                        )
                    previous["refs"].append(reference)
                else:
                    records[identity] = {"values": canonical, "refs": [reference]}
        result = list(records.values())
        if not result:
            add_issue(f"{kind} 在部门和日期范围内没有可用记录；不能将缺失当成零")
            needs_input = True
        return result

    # Selecting two revisions of the same logical file is ambiguous even if their
    # changed rows would otherwise look like unrelated records.
    series = {}
    for material in materials:
        key = (material["kind"], material["name"])
        if key in series and series[key] != material["id"]:
            add_issue("同名同分类材料选择了多个版本，请只选一个版本", material["name"], "error")
        series[key] = material["id"]

    if "projects" in groups:
        records = collect("projects")
        latest = {}
        for record in records:
            values = record["values"]
            previous = latest.get(values["project_id"])
            if previous is None or values["snapshot_date"] > previous["values"]["snapshot_date"]:
                latest[values["project_id"]] = record
        selected = list(latest.values())
        completed = [record for record in selected if record["values"]["status"] == "completed"]
        limited = ["仅反映所选材料在结束日前可识别的项目，不代表部门完整期末项目存量"]
        count = len(selected) if selected else None
        metric(
            "project_count",
            "可识别项目数",
            count,
            "个",
            "每个项目取结束日前最新有效快照后计数",
            selected,
            limited,
        )
        metric(
            "completed_project_count",
            "最新快照已完成项目数",
            len(completed) if count else None,
            "个",
            "最新快照状态为已完成的可识别项目数",
            selected,
            limited,
        )
        metric(
            "completion_rate",
            "可识别项目完成率",
            len(completed) / count if count else None,
            "ratio",
            "最新快照已完成数 ÷ 可识别项目数",
            selected,
            limited,
        )
        missing_completion = any(not record["values"]["completed_date"] for record in completed)
        period_limitations = list(limited)
        if missing_completion:
            period_limitations.append("已完成项目缺少实际完成日期，无法核验本期完成数")
            add_issue(period_limitations[-1])
        period_completed = sum(
            start <= record["values"]["completed_date"] < end for record in completed
        )
        metric(
            "completed_in_period",
            "可核验的本期完成项目数",
            None if not count or missing_completion else period_completed,
            "个",
            "最新快照为已完成且实际完成日期在报告期间内的项目数",
            selected,
            period_limitations,
            required=False,
        )

    if "attendance" in groups:
        records = collect("attendance")
        sample_limitations = ["仅为所选材料覆盖的人日样本，不等于部门整个期间的出勤率"]
        complete = bool(records) and all(
            record["values"][field] is not None
            for record in records
            for field in ("planned_hours", "actual_hours")
        )
        totals = {}
        for field in ("planned_hours", "actual_hours"):
            totals[field] = (
                sum(record["values"][field] for record in records)
                if records and all(record["values"][field] is not None for record in records)
                else None
            )
        credited = (
            sum(
                min(record["values"]["planned_hours"], record["values"]["actual_hours"])
                for record in records
            )
            if complete
            else None
        )
        excess = (
            sum(
                max(record["values"]["actual_hours"] - record["values"]["planned_hours"], 0)
                for record in records
            )
            if complete
            else None
        )
        denominator = totals["planned_hours"]
        if records and not complete:
            add_issue("考勤存在缺失工时，缺失值不按零处理")
        if denominator == 0:
            add_issue("计划工时合计为零，无法计算出勤率")
        metric(
            "person_days",
            "已提供样本人日数",
            len(records) if records else None,
            "人日",
            "部门和期间内去重的人员 × 日期记录数",
            records,
            sample_limitations,
        )
        metric(
            "sample_planned_hours",
            "已提供样本计划工时",
            denominator,
            "小时",
            "全部样本计划工时合计；请假不扣减分母",
            records,
            sample_limitations,
        )
        metric(
            "sample_actual_hours",
            "已提供样本实际工时",
            totals["actual_hours"],
            "小时",
            "全部样本实际工时合计",
            records,
            sample_limitations,
        )
        metric(
            "sample_credited_hours",
            "已提供样本计入出勤工时",
            credited,
            "小时",
            "逐人逐日 min(计划工时, 实际工时) 后合计",
            records,
            sample_limitations,
        )
        metric(
            "sample_excess_hours",
            "已提供样本超计划工时",
            excess,
            "小时",
            "逐人逐日 max(实际工时 − 计划工时, 0) 后合计，不增加出勤率",
            records,
            sample_limitations,
        )
        metric(
            "sample_attendance_rate",
            "已提供样本出勤率",
            credited / denominator if complete and denominator and credited is not None else None,
            "ratio",
            "样本计入出勤工时 ÷ 样本计划工时",
            records,
            sample_limitations,
        )
        leave_complete = bool(records) and all(
            record["values"]["leave_hours"] is not None for record in records
        )
        leave_limitations = list(sample_limitations)
        if not leave_complete:
            leave_limitations.append("部分或全部样本未提供请假工时，不能将缺失请假工时记作零")
        metric(
            "sample_leave_hours",
            "已提供样本请假工时",
            sum(record["values"]["leave_hours"] for record in records) if leave_complete else None,
            "小时",
            "全部样本明确填写请假工时后合计，单独列示且不扣计划工时分母",
            records,
            leave_limitations,
            required=False,
        )
        expected = {(person, day) for person in roster for day in work_dates}
        actual = {
            (record["values"]["person_id"], record["values"]["date"]): record for record in records
        }
        population_records = [actual[key] for key in sorted(expected) if key in actual]
        complete_population_records = [
            record
            for record in population_records
            if all(
                record["values"][field] is not None for field in ("planned_hours", "actual_hours")
            )
        ]
        coverage = len(complete_population_records) / len(expected) if expected else None
        population_complete = (
            bool(expected)
            and len(population_records) == len(expected)
            and all(
                record["values"][field] is not None
                for record in population_records
                for field in ("planned_hours", "actual_hours")
            )
        )
        population_planned = (
            sum(record["values"]["planned_hours"] for record in population_records)
            if population_complete
            else None
        )
        population_credited = (
            sum(
                min(record["values"]["planned_hours"], record["values"]["actual_hours"])
                for record in population_records
            )
            if population_complete
            else None
        )
        population_limits = []
        if not expected:
            population_limits.append(
                "未同时提供应到人员名单和工作日期，无法核验整体覆盖率及整体出勤率"
            )
        elif not population_complete:
            population_limits.append("应到人员 × 工作日期尚未完全覆盖，或对应工时不完整")
        elif not population_planned:
            population_limits.append("应到范围计划工时合计为零，整体出勤率无定义")
        if population_limits:
            add_issue(population_limits[0])
        metric(
            "attendance_coverage",
            "声明排班范围完整记录覆盖率",
            coverage,
            "ratio",
            "工时完整的应到人日数 ÷ (明确名单人数 × 工作日期数)，不推断整季度覆盖",
            population_records,
            population_limits,
            required=bool(expected),
        )
        metric(
            "attendance_rate",
            "声明排班范围出勤率",
            population_credited / population_planned
            if population_complete and population_planned and population_credited is not None
            else None,
            "ratio",
            "明确声明的排班范围完全覆盖且工时完整时，计入出勤工时 ÷ 计划工时；不代表整季度",
            population_records,
            population_limits,
            required=bool(expected),
        )

    if "achievements" in groups:
        records = collect("achievements")
        limitations = ["只统计所选材料中可识别的成果；不推断未提供的部门成果"]
        metric(
            "achievement_count",
            "可识别成果数",
            len(records) if records else None,
            "项",
            "按成果编号去重，限定部门与期间",
            records,
            limitations,
        )
        categories = sorted({record["values"].get("category", "") for record in records})
        for index, category in enumerate(categories):
            selected = [
                record for record in records if record["values"].get("category", "") == category
            ]
            metric(
                f"achievement_category_{index}",
                f"成果分类：{category or '未分类'}",
                len(selected),
                "项",
                "该分类下去重成果数",
                selected,
                limitations,
            )

    if "satisfaction" in groups:
        all_records = collect("satisfaction")
        records = [record for record in all_records if record["values"]["valid"]]
        excluded = len(all_records) - len(records)
        if excluded:
            add_issue(f"已剔除 {excluded} 条标记为无效的满意度反馈")
        scales = sorted(
            {(record["values"]["scale_min"], record["values"]["scale_max"]) for record in records}
        )
        if not scales:
            metric(
                "satisfaction_mean_0",
                "满意度平均分",
                None,
                "分",
                "按量表分别计算有效反馈算术平均，不混合不同量表",
                all_records,
                ["范围内没有有效满意度反馈，无法计算平均值"],
            )
            metric(
                "satisfaction_count_0",
                "有效满意度样本数",
                0 if all_records else None,
                "条",
                "按编号去重后的有效反馈数；明确无效反馈全部被剔除时为零条，零条不等于零分",
                all_records,
                ["缺少有效反馈"],
            )
        for index, (lower, upper) in enumerate(scales):
            selected = [
                record
                for record in records
                if (record["values"]["scale_min"], record["values"]["scale_max"]) == (lower, upper)
            ]
            label = f"{lower:g}–{upper:g} 量表"
            limitations = ["仅代表所选有效反馈样本；不同量表单独计算"]
            # Dividing before summing avoids unnecessary overflow for large finite scores.
            mean = sum(record["values"]["score"] / len(selected) for record in selected)
            metric(
                f"satisfaction_mean_{index}",
                f"满意度平均分（{label}）",
                mean,
                "分",
                "该量表有效反馈分数合计 ÷ 有效反馈数",
                selected,
                limitations,
            )
            metric(
                f"satisfaction_count_{index}",
                f"满意度样本数（{label}）",
                len(selected),
                "条",
                "该量表按反馈编号去重后的有效反馈数",
                selected,
                limitations,
            )

    invalid = any(item["severity"] == "error" for item in issues)
    if invalid:
        for item in metrics:
            item["value"] = None
            item["limitations"].append(
                "材料存在冲突或无效记录，本次统计不能用于报告，请修正材料后重新统计"
            )
    return dict(
        status="invalid_data" if invalid else "needs_input" if needs_input else "ready",
        metrics=metrics,
        issues=issues,
    )


def create_statistics_router(connection, material_service):
    router = APIRouter()
    with connection() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS statistics_snapshots (
                id TEXT PRIMARY KEY, workspace TEXT NOT NULL, report_id TEXT NOT NULL,
                payload TEXT NOT NULL
            )
        """)
        db.execute(
            "CREATE INDEX IF NOT EXISTS statistics_report "
            "ON statistics_snapshots(workspace,report_id)"
        )

    def report_row(db, report_id, workspace):
        report = db.execute(
            "SELECT * FROM reports WHERE id=? AND workspace=?", (report_id, workspace)
        ).fetchone()
        if report is None:
            raise HTTPException(404, "未找到该工作区中的报告")
        return dict(report)

    @router.post("/api/v1/reports/{report_id}/statistics", status_code=201)
    def compute_statistics(
        report_id: str,
        request: StatisticsInput,
        x_workspace: Annotated[Workspace, Header()] = "normal",
    ):
        # One transaction freezes the report version and material rows used. A
        # concurrent draft update cannot silently change the scope during this read.
        with connection() as db:
            db.execute("BEGIN IMMEDIATE")
            report = report_row(db, report_id, x_workspace)
            if request.expected_version != report["version"]:
                raise HTTPException(409, "报告已更新，请刷新后按当前版本重新统计")
            if any(
                not report["start_date"] <= day < report["end_date"]
                for day in request.attendance_dates
            ):
                raise HTTPException(422, "工作日期须位于报告起止期间内，且不包含结束日")
            materials, series = [], set()
            for material_id in request.material_ids:
                # Read the immutable rows in this same transaction instead of using
                # the truncated preview or opening a new MaterialService connection.
                row = db.execute(
                    "SELECT * FROM material_versions WHERE id=? AND workspace=?",
                    (material_id, x_workspace),
                ).fetchone()
                if row is None:
                    raise HTTPException(404, "未找到该工作区中已确认的材料")
                payload = json.loads(row["payload"])
                key = (payload["name"], payload["kind"])
                if key in series:
                    raise HTTPException(422, "同名同分类材料只能选择一个版本，请取消其他版本")
                series.add(key)
                materials.append(dict(payload, rows=json.loads(row["rows_json"])))
            result = calculate_statistics(
                report,
                materials,
                request.groups,
                request.attendance_roster,
                request.attendance_dates,
            )
            snapshot = dict(
                id=uuid4().hex,
                workspace=x_workspace,
                report_id=report_id,
                report_version=report["version"],
                department=report["department"],
                start_date=report["start_date"],
                end_date=report["end_date"],
                policy_version=POLICY_VERSION,
                created_at=datetime.now(UTC).isoformat(),
                material_ids=request.material_ids,
                materials=[
                    {key: material[key] for key in ("id", "name", "kind", "version", "sha256")}
                    for material in materials
                ],
                groups=request.groups,
                attendance_roster=request.attendance_roster,
                attendance_dates=request.attendance_dates,
                **result,
            )
            db.execute(
                "INSERT INTO statistics_snapshots VALUES(?,?,?,?)",
                (snapshot["id"], x_workspace, report_id, canonical_json(snapshot)),
            )
        return snapshot

    @router.get("/api/v1/reports/{report_id}/statistics")
    def list_statistics(report_id: str, x_workspace: Annotated[Workspace, Header()] = "normal"):
        with connection() as db:
            report_row(db, report_id, x_workspace)
            rows = db.execute(
                "SELECT payload FROM statistics_snapshots WHERE workspace=? AND report_id=? "
                "ORDER BY rowid DESC",
                (x_workspace, report_id),
            ).fetchall()
        return {"items": [json.loads(row[0]) for row in rows]}

    return router
