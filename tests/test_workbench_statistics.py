"""Statistics are reproducible, complete-input calculations, never model estimates."""

import csv
import hashlib
import io
import sqlite3
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from office_agents.workbench.materials import MaterialService
from office_agents.workbench.statistics import (
    StatisticsInput,
    calculate_statistics,
    create_statistics_router,
)

REPORT = dict(department="技术部", start_date="2026-04-01", end_date="2026-07-01")


def material(kind, rows, name=None, identifier="m1", version=1, mapping=None):
    return dict(
        id=identifier,
        name=name or kind + ".csv",
        kind=kind,
        version=version,
        sha256=hashlib.sha256(repr(rows).encode()).hexdigest(),
        mapping=mapping or {key: key for row in rows for key in row},
        rows=[dict(location=f"行 {index}", values=row) for index, row in enumerate(rows, 2)],
    )


def project(identifier="P1", snapshot="2026-06-30", status="completed", **changes):
    return dict(
        project_id=identifier,
        department="技术部",
        effective_date="2026-03-01",
        snapshot_date=snapshot,
        status=status,
        progress="100",
        completed_date="2026-06-01" if status == "completed" else "",
        **changes,
    )


def attendance(person="A", day="2026-06-29", planned="8", actual="8", **changes):
    return dict(
        person_id=person,
        department="技术部",
        date=day,
        planned_hours=planned,
        actual_hours=actual,
        **changes,
    )


def achievement(identifier="A1", day="2026-06-29", **changes):
    return dict(
        achievement_id=identifier,
        department="技术部",
        date=day,
        category="交付",
        name="已完成成果",
        **changes,
    )


def feedback(identifier="F1", score="4", lower="1", upper="5", **changes):
    return dict(
        feedback_id=identifier,
        department="技术部",
        date="2026-06-29",
        score=score,
        scale_min=lower,
        scale_max=upper,
        **changes,
    )


def values(result):
    return {metric["id"]: metric["value"] for metric in result["metrics"]}


def test_projects_select_latest_before_exclusive_end_and_do_not_claim_full_inventory():
    rows = [
        project(snapshot="2026-04-15", status="in_progress"),
        project(),
        project(identifier="P2", status="进行中"),
        project(identifier="P3", snapshot="2026-07-01"),
        dict(project(identifier="P4"), department="行政部"),
        dict(project(identifier="P5"), effective_date="2026-07-01", snapshot_date="2026-07-01"),
    ]
    result = calculate_statistics(REPORT, [material("projects", rows)], ["projects"])
    assert result["status"] == "ready"
    assert values(result) == dict(
        project_count=2, completed_project_count=1, completion_rate=0.5, completed_in_period=1
    )
    metric = result["metrics"][0]
    assert {ref["location"] for ref in metric["source_refs"]} == {"行 3", "行 4"}
    assert "不代表部门完整期末" in metric["limitations"][0]


def test_project_period_completion_is_not_snapshot_completed_count():
    rows = [dict(project(), completed_date="2026-03-20"), project(identifier="P2")]
    result = calculate_statistics(REPORT, [material("projects", rows)], ["projects"])
    assert values(result)["completed_project_count"] == 2
    assert values(result)["completed_in_period"] == 1
    rows[1]["completed_date"] = ""
    missing = calculate_statistics(REPORT, [material("projects", rows)], ["projects"])
    assert values(missing)["completed_project_count"] == 2
    assert values(missing)["completed_in_period"] is None
    assert missing["status"] == "ready"


@pytest.mark.parametrize(
    "kind,record",
    [
        ("projects", project()),
        ("attendance", attendance()),
        ("achievements", achievement()),
        ("satisfaction", feedback()),
    ],
)
def test_identical_business_records_across_files_deduplicate_but_retain_every_source(kind, record):
    first = material(kind, [record])
    second = material(kind, [dict(record)], name="另一份.csv", identifier="m2")
    result = calculate_statistics(REPORT, [first, second], [kind])
    counts = values(result)
    key = {
        "projects": "project_count",
        "attendance": "person_days",
        "achievements": "achievement_count",
        "satisfaction": "satisfaction_count_0",
    }[kind]
    assert counts[key] == 1
    assert {ref["material_id"] for ref in result["metrics"][0]["source_refs"]} == {"m1", "m2"}


@pytest.mark.parametrize(
    "kind,first,changed",
    [
        ("projects", project(), dict(project(), progress="50")),
        ("attendance", attendance(), dict(attendance(), actual_hours="4")),
        ("achievements", achievement(), dict(achievement(), name="不同成果")),
        ("satisfaction", feedback(), dict(feedback(), score="3")),
    ],
)
def test_conflicting_business_records_fail_closed_instead_of_overwriting(kind, first, changed):
    result = calculate_statistics(
        REPORT,
        [material(kind, [first]), material(kind, [changed], name="冲突.csv", identifier="m2")],
        [kind],
    )
    assert result["status"] == "invalid_data"
    assert all(metric["value"] is None for metric in result["metrics"])
    assert any("冲突" in issue["message"] for issue in result["issues"])
    assert len(result["metrics"][0]["source_refs"]) == 2


def test_attendance_half_open_exact_department_and_overtime_cannot_inflate_rate():
    rows = [
        attendance(actual="10", leave_hours="2"),
        attendance("B", actual="6", leave_hours="2"),
        attendance("C", day="2026-07-01"),
        dict(attendance("D"), department="技术部二组"),
        attendance("E", day="2026-03-31"),
    ]
    result = calculate_statistics(REPORT, [material("attendance", rows)], ["attendance"])
    assert values(result) == dict(
        person_days=2,
        sample_planned_hours=16,
        sample_actual_hours=16,
        sample_credited_hours=14,
        sample_excess_hours=2,
        sample_attendance_rate=0.875,
        attendance_coverage=None,
        attendance_rate=None,
        sample_leave_hours=4,
    )
    assert result["status"] == "ready"
    assert (
        "请假不扣减分母"
        in next(metric for metric in result["metrics"] if metric["id"] == "sample_planned_hours")[
            "definition"
        ]
    )


@pytest.mark.parametrize(
    "planned,actual,planned_total,actual_total",
    [("", "8", None, 8), ("8", "", 8, None), ("0", "0", 0, 0)],
)
def test_missing_and_zero_hours_do_not_manufacture_a_rate(
    planned, actual, planned_total, actual_total
):
    result = calculate_statistics(
        REPORT,
        [material("attendance", [attendance(planned=planned, actual=actual)])],
        ["attendance"],
        ["A"],
        ["2026-06-29"],
    )
    metrics = values(result)
    assert metrics["sample_planned_hours"] == planned_total
    assert metrics["sample_actual_hours"] == actual_total
    assert metrics["sample_attendance_rate"] is None
    assert metrics["attendance_rate"] is None
    assert metrics["attendance_coverage"] == (1 if planned == actual == "0" else 0)


def test_declared_roster_requires_all_person_days_and_excludes_unlisted_staff():
    rows = [attendance(), attendance("B", actual="6"), attendance("C", actual="0")]
    complete = calculate_statistics(
        REPORT, [material("attendance", rows)], ["attendance"], ["A", "B"], ["2026-06-29"]
    )
    assert values(complete)["attendance_coverage"] == 1
    assert values(complete)["attendance_rate"] == 0.875
    assert complete["status"] == "ready"
    missing = calculate_statistics(
        REPORT, [material("attendance", rows[:1])], ["attendance"], ["A", "B"], ["2026-06-29"]
    )
    assert values(missing)["attendance_coverage"] == 0.5
    assert values(missing)["attendance_rate"] is None
    metric = next(item for item in complete["metrics"] if item["id"] == "attendance_rate")
    assert "声明排班范围" in metric["label"]
    assert "不代表整季度" in metric["definition"]


def test_achievements_use_all_rows_not_twenty_row_preview_and_classify():
    rows = [
        dict(achievement(f"A{index}"), category="软件" if index < 21 else "文档")
        for index in range(26)
    ]
    result = calculate_statistics(REPORT, [material("achievements", rows)], ["achievements"])
    assert values(result)["achievement_count"] == 26
    assert sorted(
        value for key, value in values(result).items() if key.startswith("achievement_category")
    ) == [5, 21]
    assert len(result["metrics"][0]["source_refs"]) == 26
    assert result["metrics"][0]["source_refs"][-1]["location"] == "行 27"


def test_satisfaction_excludes_invalid_and_separates_scales():
    rows = [
        feedback(),
        feedback("F2", "2"),
        feedback("F3", "90", "0", "100"),
        feedback("F4", "1", valid="false"),
    ]
    result = calculate_statistics(REPORT, [material("satisfaction", rows)], ["satisfaction"])
    assert values(result) == dict(
        satisfaction_mean_0=90,
        satisfaction_count_0=1,
        satisfaction_mean_1=3,
        satisfaction_count_1=2,
    )
    assert result["status"] == "ready"
    assert any("剔除 1 条" in item["message"] for item in result["issues"])
    assert len(result["metrics"][2]["source_refs"]) == 2


def test_real_zero_satisfaction_is_valid_not_missing():
    result = calculate_statistics(
        REPORT, [material("satisfaction", [feedback(score="0", lower="0")])], ["satisfaction"]
    )
    assert values(result)["satisfaction_mean_0"] == 0
    assert result["status"] == "ready"


def test_all_invalid_satisfaction_and_missing_requested_group_need_input():
    result = calculate_statistics(
        REPORT, [material("satisfaction", [feedback(valid="false")])], ["satisfaction", "projects"]
    )
    assert result["status"] == "needs_input"
    assert values(result)["satisfaction_count_0"] == 0
    assert values(result)["satisfaction_mean_0"] is None
    assert values(result)["project_count"] is None


@pytest.mark.parametrize(
    "row",
    [
        dict(project(), status="未知状态"),
        dict(project(), progress="nan"),
        dict(project(), completed_date="2026-07-02"),
    ],
)
def test_unusable_project_values_are_invalid_data(row):
    result = calculate_statistics(REPORT, [material("projects", [row])], ["projects"])
    assert result["status"] == "invalid_data"
    assert all(value is None for value in values(result).values())


def test_chinese_column_mapping_is_used_and_provenance_preserves_original_column_names():
    row = {"编号": "A1", "单位": "技术部", "日期": "2026-06-01", "分类": "专利", "标题": "合成成果"}
    mapping = dict(
        achievement_id="编号", department="单位", date="日期", category="分类", name="标题"
    )
    result = calculate_statistics(
        REPORT, [material("achievements", [row], mapping=mapping)], ["achievements"]
    )
    assert values(result)["achievement_count"] == 1
    assert set(result["metrics"][0]["source_refs"][0]["fields"]) == set(row)


def test_notes_cannot_be_mined_for_numeric_statistics():
    notes = material("notes", [dict(text="本季度完成999个项目，出勤率100%")])
    result = calculate_statistics(
        REPORT, [notes], ["projects", "attendance", "achievements", "satisfaction"]
    )
    assert result["status"] == "needs_input"
    assert all(value is None for value in values(result).values())


@pytest.fixture
def statistics_api(tmp_path):
    database = tmp_path / "statistics.sqlite3"

    @contextmanager
    def connection():
        db = sqlite3.connect(database)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    with connection() as db:
        db.execute(
            "CREATE TABLE reports(id TEXT PRIMARY KEY, workspace TEXT, department TEXT, "
            "start_date TEXT, end_date TEXT, version INTEGER)"
        )
        db.executemany(
            "INSERT INTO reports VALUES(?,?,?,?,?,?)",
            [
                ("r1", "normal", "技术部", "2026-04-01", "2026-07-01", 1),
                ("rd", "demo", "技术部", "2026-04-01", "2026-07-01", 1),
            ],
        )
    service = MaterialService(connection, tmp_path / "materials")
    app = FastAPI()
    app.include_router(create_statistics_router(connection, service))

    def import_material(kind, rows, name="数据.csv", workspace="normal"):
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
        draft = service.stage_import(stream.getvalue().encode(), name, kind, workspace)
        confirmed = service.confirm(draft["id"], workspace, {"mapping": draft["suggested_mapping"]})
        return confirmed, draft

    with TestClient(app) as client:
        yield client, connection, service, import_material, app


def post_request(client, materials, report="r1", **changes):
    return client.post(
        f"/api/v1/reports/{report}/statistics",
        json=dict(
            expected_version=1,
            material_ids=[item["id"] for item in materials],
            groups=["achievements"],
            **changes,
        ),
    )


def test_api_uses_full_rows_freezes_input_and_keeps_report_version(statistics_api):
    client, connection, _, import_material, _ = statistics_api
    first, _ = import_material("achievements", [achievement(f"A{index}") for index in range(27)])
    assert len(first["preview"]) == 20
    response = post_request(client, [first])
    assert response.status_code == 201, response.text
    snapshot = response.json()
    assert values(snapshot)["achievement_count"] == 27
    assert snapshot["report_version"] == 1
    assert snapshot["policy_version"] == "2026-10-v1"
    assert snapshot["materials"] == [
        {key: first[key] for key in ("id", "name", "kind", "version", "sha256")}
    ]
    second, _ = import_material("achievements", [achievement("new")])
    assert second["version"] == 2
    assert client.get("/api/v1/reports/r1/statistics").json()["items"] == [snapshot]
    with connection() as db:
        assert db.execute("SELECT version FROM reports WHERE id='r1'").fetchone()[0] == 1
        db.execute("UPDATE reports SET version=2 WHERE id='r1'")
    stale = post_request(client, [second])
    assert stale.status_code == 409
    assert client.get("/api/v1/reports/r1/statistics").json()["items"] == [snapshot]


def test_api_preserves_snapshots_on_restart_and_orders_newest_first(statistics_api):
    client, connection, service, import_material, _ = statistics_api
    item, _ = import_material("achievements", [achievement()])
    first = post_request(client, [item]).json()
    second = post_request(client, [item]).json()
    restarted = FastAPI()
    restarted.include_router(create_statistics_router(connection, service))
    with TestClient(restarted) as restarted_client:
        assert restarted_client.get("/api/v1/reports/r1/statistics").json()["items"] == [
            second,
            first,
        ]


def test_api_isolates_reports_materials_and_unconfirmed_imports(statistics_api):
    client, _, service, import_material, _ = statistics_api
    confirmed, _ = import_material("achievements", [achievement()])
    response = client.post(
        "/api/v1/reports/rd/statistics",
        headers={"X-Workspace": "demo"},
        json=dict(expected_version=1, material_ids=[confirmed["id"]], groups=["achievements"]),
    )
    assert response.status_code == 404
    assert (
        client.get("/api/v1/reports/r1/statistics", headers={"X-Workspace": "demo"}).status_code
        == 404
    )
    assert post_request(client, [confirmed], report="missing").status_code == 404
    staged = service.stage_import(b"text", "notes.txt", "notes", "normal")
    assert post_request(client, [staged]).status_code == 404
    assert client.get("/api/v1/reports/r1/statistics").json() == {"items": []}


def test_api_rejects_two_revisions_of_same_file(statistics_api):
    client, _, _, import_material, _ = statistics_api
    first, _ = import_material("achievements", [achievement()])
    second, _ = import_material("achievements", [achievement("A2")])
    assert post_request(client, [first, second]).status_code == 422


@pytest.mark.parametrize(
    "changes",
    [
        dict(expected_version=0),
        dict(expected_version=True),
        dict(material_ids=[]),
        dict(material_ids=["id", "id"]),
        dict(groups=[]),
        dict(groups=["projects", "projects"]),
        dict(groups=["unknown"]),
        dict(attendance_roster=["A"]),
        dict(attendance_dates=["2026-06-01"]),
        dict(attendance_roster=["A", "A"], attendance_dates=["2026-06-01"]),
        dict(attendance_roster=["A"], attendance_dates=["2026-06-01", "2026-06-01"]),
        dict(attendance_roster=[""], attendance_dates=["2026-06-01"]),
        dict(attendance_roster=["A"], attendance_dates=["2026-02-30"]),
        dict(attendance_roster=["A"], attendance_dates=["2026-07-01"]),
        dict(unexpected="field"),
    ],
)
def test_request_validation_prevents_ambiguous_or_out_of_scope_calculations(
    statistics_api, changes
):
    client, _, _, import_material, _ = statistics_api
    item, _ = import_material("achievements", [achievement()])
    payload = dict(expected_version=1, material_ids=[item["id"]], groups=["achievements"])
    payload.update(changes)
    assert client.post("/api/v1/reports/r1/statistics", json=payload).status_code == 422
    assert client.get("/api/v1/reports/r1/statistics").json()["items"] == []


def test_declared_population_cross_product_is_bounded():
    with pytest.raises(ValueError, match="20000"):
        StatisticsInput(
            expected_version=1,
            material_ids=["m"],
            groups=["attendance"],
            attendance_roster=[f"P{index}" for index in range(1000)],
            attendance_dates=[f"2026-06-{index:02d}" for index in range(1, 22)],
        )


def test_optional_achievement_link_missing_and_empty_do_not_create_a_conflict():
    first = material("achievements", [achievement()])
    second = material(
        "achievements", [achievement(project_id="")], name="补充.csv", identifier="m2"
    )
    result = calculate_statistics(REPORT, [first, second], ["achievements"])
    assert result["status"] == "ready"
    assert values(result)["achievement_count"] == 1
    assert len(result["metrics"][0]["source_refs"]) == 2


def test_optional_leave_missing_is_unknown_not_zero_and_does_not_block_sample():
    result = calculate_statistics(
        REPORT,
        [material("attendance", [attendance(), attendance("B", leave_hours="0")])],
        ["attendance"],
    )
    assert result["status"] == "ready"
    assert values(result)["sample_leave_hours"] is None
    assert values(result)["sample_attendance_rate"] == 1
    item = next(item for item in result["metrics"] if item["id"] == "sample_leave_hours")
    assert any("不能" in text for text in item["limitations"])


def test_project_optional_period_delivery_can_be_unknown_without_blocking_end_snapshot():
    result = calculate_statistics(
        REPORT, [material("projects", [dict(project(), completed_date="")])], ["projects"]
    )
    assert result["status"] == "ready"
    assert values(result)["completion_rate"] == 1
    assert values(result)["completed_in_period"] is None


def test_core_same_series_revisions_are_invalid_in_addition_to_api_rejection():
    first = material("achievements", [achievement()])
    second = material("achievements", [achievement("A2")], identifier="m2", version=2)
    result = calculate_statistics(REPORT, [first, second], ["achievements"])
    assert result["status"] == "invalid_data"
    assert values(result)["achievement_count"] is None
