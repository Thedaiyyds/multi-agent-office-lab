"""Large fictional cases exercise the production import and statistical contracts."""

import csv
import hashlib
import io
import json
import runpy
import sqlite3
from collections import Counter
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import pytest

from office_agents.workbench.materials import MaterialService
from office_agents.workbench.statistics import calculate_statistics

CASES = Path(__file__).resolve().parents[1] / "data" / "office-cases"
FILES = {
    "technical-q2/项目进度.csv": "projects",
    "technical-q2/人员考勤.csv": "attendance",
    "technical-q2/成果统计.csv": "achievements",
    "technical-q2/工作说明.txt": "notes",
    "administration-q1/满意度.csv": "satisfaction",
    "administration-q1/服务说明.txt": "notes",
}
TECH = dict(department="技术部", start_date="2026-04-01", end_date="2026-07-01")
ADMIN = dict(department="行政部", start_date="2026-01-01", end_date="2026-04-01")


def raw_rows(name):
    return list(csv.DictReader(io.StringIO((CASES / name).read_text(encoding="utf-8"))))


def metric_values(result):
    return {metric["id"]: metric["value"] for metric in result["metrics"]}


@pytest.fixture
def imported(tmp_path):
    @contextmanager
    def connection():
        db = sqlite3.connect(tmp_path / "materials.db")
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    service = MaterialService(connection, tmp_path / "files")
    materials = {}
    for relative, kind in FILES.items():
        path = CASES / relative
        scope = TECH if relative.startswith("technical") else ADMIN
        draft = service.stage_import(path.read_bytes(), path.name, kind, "normal", **scope)
        assert not draft["issues"]
        confirmed = service.confirm(
            draft["id"], "normal", dict(mapping=draft["suggested_mapping"], **scope)
        )
        assert not confirmed["issues"]
        stored = service.get(confirmed["id"], "normal")
        materials[relative] = dict(confirmed, rows=json.loads(stored["rows_json"]))
    return materials


def test_published_materials_and_manifest_rebuild_identically(tmp_path):
    generator = runpy.run_path(str(CASES / "generate.py"))["generate"]
    first, second = tmp_path / "first", tmp_path / "second"
    manifest = generator(first)
    assert generator(second) == manifest
    assert manifest["seed"] == "office-cases-2026-v1"
    assert manifest["fictional"] is True
    for relative in [*FILES, "manifest.json"]:
        assert (first / relative).read_bytes() == (CASES / relative).read_bytes()
        assert (first / relative).read_bytes() == (second / relative).read_bytes()
    for relative in FILES:
        data = (CASES / relative).read_bytes()
        assert manifest["files"][relative] == dict(
            sha256=hashlib.sha256(data).hexdigest(), byte_size=len(data)
        )


def test_all_rows_survive_actual_material_import_and_confirmation(imported):
    assert {name: len(material["rows"]) for name, material in imported.items()} == {
        "technical-q2/项目进度.csv": 36,
        "technical-q2/人员考勤.csv": 1560,
        "technical-q2/成果统计.csv": 42,
        "technical-q2/工作说明.txt": 18,
        "administration-q1/满意度.csv": 216,
        "administration-q1/服务说明.txt": 13,
    }
    for material in imported.values():
        assert material["source"] == "file"
        assert material["version"] == 1
        assert material["department"] in {"技术部", "行政部"}
        assert material["mapping"] if material["kind"] != "notes" else not material["mapping"]


def test_project_history_owners_and_achievements_form_consistent_business_records():
    projects = raw_rows("technical-q2/项目进度.csv")
    achievements = raw_rows("technical-q2/成果统计.csv")
    assert len({row["project_id"] for row in projects}) == 12
    assert Counter(row["snapshot_date"] for row in projects) == {
        "2026-04-30": 12,
        "2026-05-31": 12,
        "2026-06-30": 12,
    }
    for identifier in {row["project_id"] for row in projects}:
        history = sorted(
            [row for row in projects if row["project_id"] == identifier],
            key=lambda row: row["snapshot_date"],
        )
        assert len(history) == 3
        assert len({(row["owner_id"], row["team"], row["effective_date"]) for row in history}) == 1
        progress = [float(row["progress"]) for row in history]
        assert progress == sorted(progress)
        for row in history:
            assert row["effective_date"] <= row["snapshot_date"]
            if row["status"] == "completed":
                assert row["effective_date"] <= row["completed_date"] <= row["snapshot_date"]
                assert float(row["progress"]) == 100
            else:
                assert row["completed_date"] == ""
                assert float(row["progress"]) < 100
    latest = {row["project_id"]: row for row in projects if row["snapshot_date"] == "2026-06-30"}
    assert Counter(row["status"] for row in latest.values()) == {
        "completed": 6,
        "in_progress": 5,
        "paused": 1,
    }
    assert len({row["achievement_id"] for row in achievements}) == 42
    assert Counter(row["category"] for row in achievements) == {
        "技术文档": 12,
        "质量改进": 12,
        "运维优化": 12,
        "项目交付": 6,
    }
    assert Counter(row["date"][:7] for row in achievements) == {
        "2026-04": 13,
        "2026-05": 14,
        "2026-06": 15,
    }
    for row in achievements:
        project = latest[row["project_id"]]
        assert row["owner_id"] == project["owner_id"]
        assert "2026-04-01" <= row["date"] < "2026-07-01"
        if row["category"] == "项目交付":
            assert row["date"] == project["completed_date"]


def test_attendance_is_a_complete_fictional_roster_calendar_with_reconciled_hours():
    rows = raw_rows("technical-q2/人员考勤.csv")
    identities = {(row["person_id"], row["date"]) for row in rows}
    assert len(identities) == len(rows) == 1560
    roster = {f"SYN-U{index:03}" for index in range(1, 25)}
    dates = {row["date"] for row in rows}
    assert len(dates) == 65
    assert Counter(day[:7] for day in dates) == {"2026-04": 22, "2026-05": 21, "2026-06": 22}
    assert all(date.fromisoformat(day).weekday() < 5 for day in dates)
    assert identities == {(person, day) for person in roster for day in dates}
    assert Counter(row["team"] for row in rows) == dict.fromkeys(
        ["平台工程组", "业务应用组", "数据工程组", "质量运维组"], 390
    )
    assert Counter(row["attendance_status"] for row in rows) == {
        "正常": 1177,
        "超计划": 184,
        "迟到": 83,
        "缺勤": 9,
        "请假": 107,
    }
    for row in rows:
        assert row["project_id"] == f"SYN-P{(int(row['person_id'][5:]) + 1) // 2:03}"
        actual = float(row["actual_hours"])
        leave, absent = float(row["leave_hours"]), float(row["absent_hours"])
        late = float(row["late_minutes"])
        if actual <= 8:
            assert actual + leave + absent + late / 60 == 8
        else:
            assert leave == absent == late == 0
    assert sum(float(row["absent_hours"]) for row in rows) == 72
    assert sum(float(row["late_minutes"]) for row in rows) == 1830


def test_production_statistics_reproduce_large_technical_case_without_false_overall_claim(imported):
    # Both departments are supplied deliberately: the production scope must filter them correctly.
    result = calculate_statistics(
        TECH, list(imported.values()), ["projects", "attendance", "achievements"]
    )
    assert result["status"] == "ready"
    values = metric_values(result)
    assert {
        key: values[key]
        for key in (
            "project_count",
            "completed_project_count",
            "completed_in_period",
            "completion_rate",
            "person_days",
            "sample_planned_hours",
            "sample_actual_hours",
            "sample_credited_hours",
            "sample_excess_hours",
            "sample_leave_hours",
            "achievement_count",
        )
    } == dict(
        project_count=12,
        completed_project_count=6,
        completed_in_period=6,
        completion_rate=0.5,
        person_days=1560,
        sample_planned_hours=12480,
        sample_actual_hours=12190.5,
        sample_credited_hours=11899.5,
        sample_excess_hours=291,
        sample_leave_hours=478,
        achievement_count=42,
    )
    assert values["sample_attendance_rate"] == pytest.approx(11899.5 / 12480)
    assert values["attendance_coverage"] is None
    assert values["attendance_rate"] is None
    attendance_metric = next(
        metric for metric in result["metrics"] if metric["id"] == "person_days"
    )
    assert len(attendance_metric["source_refs"]) == 1560


def test_explicit_roster_and_calendar_are_required_before_declared_population_claim(imported):
    manifest = json.loads((CASES / "manifest.json").read_text())
    scope = manifest["technical_q2"]["attendance_scope"]
    materials = [imported["technical-q2/人员考勤.csv"]]
    result = calculate_statistics(
        TECH, materials, ["attendance"], scope["roster"], scope["work_dates"]
    )
    assert result["status"] == "ready"
    assert metric_values(result)["attendance_coverage"] == 1
    assert metric_values(result)["attendance_rate"] == pytest.approx(11899.5 / 12480)
    # A single missing day is not repaired by the fact that the remaining file is large.
    incomplete = dict(materials[0], rows=materials[0]["rows"][1:])
    result = calculate_statistics(
        TECH, [incomplete], ["attendance"], scope["roster"], scope["work_dates"]
    )
    assert result["status"] == "needs_input"
    assert metric_values(result)["attendance_coverage"] == pytest.approx(1559 / 1560)
    assert metric_values(result)["attendance_rate"] is None


def test_feedback_has_service_context_invalid_reasons_and_independent_expected_distribution(
    imported,
):
    rows = raw_rows("administration-q1/满意度.csv")
    assert len(rows) == len({row["feedback_id"] for row in rows}) == 216
    assert Counter(row["date"][:7] for row in rows) == dict.fromkeys(
        ["2026-01", "2026-02", "2026-03"], 72
    )
    assert Counter(row["service_type"] for row in rows) == {
        "会议支持": 54,
        "物业报修": 48,
        "办公用品": 38,
        "差旅支持": 32,
        "入离职支持": 26,
        "档案借阅": 18,
    }
    assert {(row["scale_min"], row["scale_max"]) for row in rows} == {("1", "5")}
    valid = [row for row in rows if row["valid"] == "true"]
    assert len(valid) == 204
    assert sum(int(row["score"]) for row in valid) == 810
    assert Counter(int(row["score"]) for row in valid) == {1: 3, 2: 9, 3: 41, 4: 89, 5: 62}
    assert Counter(row["invalid_reason"] for row in rows if row["valid"] == "false") == {
        "重复提交": 3,
        "评价场景不符": 3,
        "提交者主动撤回": 3,
        "内部测试": 3,
    }
    result = calculate_statistics(ADMIN, list(imported.values()), ["satisfaction"])
    assert result["status"] == "ready"
    assert metric_values(result)["satisfaction_count_0"] == 204
    assert metric_values(result)["satisfaction_mean_0"] == pytest.approx(810 / 204)
    assert any("12 条" in item["message"] for item in result["issues"])
    for month, score_sum in zip(range(1, 4), (252, 269, 289), strict=True):
        month_report = dict(
            ADMIN, start_date=f"2026-{month:02}-01", end_date=f"2026-{month + 1:02}-01"
        )
        monthly = calculate_statistics(month_report, list(imported.values()), ["satisfaction"])
        assert metric_values(monthly)["satisfaction_count_0"] == 68
        assert metric_values(monthly)["satisfaction_mean_0"] == pytest.approx(score_sum / 68)


def test_background_fits_existing_authorized_notes_budget():
    for name in ("technical-q2/工作说明.txt", "administration-q1/服务说明.txt"):
        text = (CASES / name).read_text(encoding="utf-8")
        assert "虚构" in text
        assert len(text) < 5000
        assert max(map(len, text.splitlines())) < 1000
    text = (CASES / "technical-q2/工作说明.txt").read_text(encoding="utf-8")
    assert "暂停" in text and "风险" in text and "后续计划" in text
    assert all(f"SYN-P{identifier:03}" in text for identifier in range(7, 13))
