"""Independent hand-counted scenarios; no API access or generated model facts."""

from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from office_agents.schemas import (
    Achievement,
    DataIssue,
    DataRequest,
    IssueMaterial,
    ProjectSnapshot,
    SourceRecord,
    SourceRef,
    ValidatedDataset,
)
from office_agents.tools.metrics import calculate_metrics, run_data_tools

SAMPLES = Path(__file__).resolve().parents[1] / "data" / "samples"


def request(department="研发部", start="2026-04-01", end="2026-07-01"):
    return DataRequest(
        department=department, start_date=start, end_date=end, data_origin="simulated"
    )


def values(result):
    return {metric.metric_id: metric.value for metric in result.metrics}


def rows(result, metric_id):
    return [
        reference.line_number
        for metric in result.metrics
        if metric.metric_id == metric_id
        for reference in metric.source_refs
    ]


def project(project_id, day, status, line, department="研发部"):
    return ProjectSnapshot(
        project_id=project_id,
        department=department,
        snapshot_date=day,
        status=status,
        progress=100 if status == "completed" else 50,
        source=SourceRef(source_id="projects.csv", line_number=line),
    )


@pytest.mark.parametrize(
    "department,start,end,expected,status,project_rows,complete_rows,achievement_rows",
    [
        ("研发部", "2026-04-01", "2026-07-01", (3, 2, 2 / 3, 2), "ok", [3, 4, 5], [3, 4], [2, 3]),
        ("研发部", "2026-01-01", "2026-04-01", (2, 1, 0.5, 1), "ok", [6, 7], [7], [4]),
        ("市场部", "2026-04-01", "2026-07-01", (1, 0, 0, 1), "ok", [8], [], [5]),
        ("研发部", "2026-07-01", "2026-10-01", (1, 0, 0, 1), "ok", [9], [], [6]),
        ("财务部", "2026-04-01", "2026-07-01", (0, 0, None, 0), "no_data", [], [], []),
        ("研发部", "2026-04-01", "2026-04-02", (1, 1, 1, 1), "ok", [4], [4], [2]),
        ("研发部", "2026-06-25", "2026-06-26", (0, 0, None, 1), "ok", [], [], [3]),
    ],
)
def test_real_samples_match_independent_hand_count_matrix(
    department, start, end, expected, status, project_rows, complete_rows, achievement_rows
):
    result = run_data_tools(SAMPLES, request(department, start, end))
    assert result.status == status
    assert result.mode == "offline"
    assert result.request.data_origin == "simulated"
    assert values(result) == dict(
        zip(
            ["project_count", "completed_project_count", "completion_rate", "achievement_count"],
            expected,
            strict=True,
        )
    )
    assert rows(result, "project_count") == project_rows
    assert rows(result, "completed_project_count") == complete_rows
    assert rows(result, "completion_rate") == project_rows
    assert rows(result, "achievement_count") == achievement_rows
    assert all(metric.definition for metric in result.metrics)
    assert all(
        metric.source_ids
        == ["achievements.csv" if metric.metric_id == "achievement_count" else "projects.csv"]
        for metric in result.metrics
    )
    assert {source.source_id: source.record_count for source in result.sources} == {
        "projects.csv": 8,
        "achievements.csv": 5,
        "issues.txt": 0,
    }
    assert len(result.issue_materials) == 1
    assert result.issue_materials[0].scope == "unfiltered"
    assert "市场部" in result.issue_materials[0].text


def test_latest_snapshot_wins_even_when_input_order_changes():
    records = [
        project("P1", "2026-06-01", "completed", 3),
        project("P1", "2026-04-01", "active", 2),
        project("P2", "2026-04-10", "completed", 4),
        project("P2", "2026-06-10", "blocked", 5),
    ]
    first = calculate_metrics(ValidatedDataset(projects=records), request())
    second = calculate_metrics(ValidatedDataset(projects=list(reversed(records))), request())
    assert values(first) == {
        "project_count": 2,
        "completed_project_count": 1,
        "completion_rate": 0.5,
        "achievement_count": 0,
    }
    assert rows(first, "project_count") == [3, 5]
    assert rows(first, "completed_project_count") == [3]
    assert first.metrics == second.metrics
    assert len(records) == 4


def test_same_project_has_separate_latest_state_in_each_quarter():
    dataset = ValidatedDataset(
        projects=[
            project("P1", "2026-03-31", "active", 2),
            project("P1", "2026-04-01", "completed", 3),
            project("P1", "2026-07-01", "blocked", 4),
        ]
    )
    q1 = calculate_metrics(dataset, request(start="2026-01-01", end="2026-04-01"))
    q2 = calculate_metrics(dataset, request())
    q3 = calculate_metrics(dataset, request(start="2026-07-01", end="2026-10-01"))
    assert [values(result)["project_count"] for result in (q1, q2, q3)] == [1, 1, 1]
    assert [values(result)["completed_project_count"] for result in (q1, q2, q3)] == [0, 1, 0]
    assert [rows(result, "project_count") for result in (q1, q2, q3)] == [[2], [3], [4]]


def test_multi_quarter_request_still_counts_each_project_once():
    result = run_data_tools(SAMPLES, request(start="2026-01-01", end="2026-07-01"))
    assert values(result) == {
        "project_count": 4,
        "completed_project_count": 3,
        "completion_rate": 0.75,
        "achievement_count": 3,
    }
    assert rows(result, "project_count") == [3, 4, 5, 7]


def test_department_matching_is_exact_not_substring():
    result = run_data_tools(SAMPLES, request(department="研发"))
    assert result.status == "no_data"
    assert values(result)["project_count"] == 0


def test_global_error_blocks_partial_metrics_and_issue_material():
    problem = DataIssue(
        severity="error", code="invalid_date", message="Invalid date.", source_id="achievements.csv"
    )
    dataset = ValidatedDataset(
        projects=[project("P1", "2026-04-01", "completed", 2)],
        issue_materials=[IssueMaterial(text="private-unfiltered-material")],
        data_issues=[problem],
        sources=[
            SourceRecord(
                source_id="projects.csv", file_name="projects.csv", sha256="a" * 64, record_count=1
            )
        ],
    )
    result = calculate_metrics(dataset, request())
    assert result.status == "invalid_data"
    assert result.metrics == []
    assert result.issue_materials == []
    assert result.data_issues == [problem]
    assert result.sources == dataset.sources
    assert "private-unfiltered-material" not in result.model_dump_json()


def test_real_validation_error_outside_filter_blocks_all_metrics(tmp_path):
    for file_name in ("projects.csv", "achievements.csv", "issues.txt"):
        (tmp_path / file_name).write_bytes((SAMPLES / file_name).read_bytes())
    with (tmp_path / "projects.csv").open("a", encoding="utf-8") as stream:
        stream.write("INVALID,市场部,2025-01-01,active,nan\n")
    result = run_data_tools(tmp_path, request())
    assert result.status == "invalid_data"
    assert result.metrics == []
    assert result.issue_materials == []
    assert any(issue.severity == "error" for issue in result.data_issues)


def test_raw_issue_material_is_unfiltered_and_preserves_whitespace(tmp_path):
    for file_name in ("projects.csv", "achievements.csv"):
        (tmp_path / file_name).write_bytes((SAMPLES / file_name).read_bytes())
    original = "\n  市场部：未按部门和季度筛选的模拟材料。  \n\n"
    (tmp_path / "issues.txt").write_text(original, encoding="utf-8")
    result = run_data_tools(tmp_path, request())
    assert result.status == "ok"
    assert result.issue_materials[0].scope == "unfiltered"
    assert result.issue_materials[0].text == original


def test_warning_is_preserved_and_does_not_block_metrics():
    warning = DataIssue(severity="warning", code="duplicate", message="Duplicate removed.")
    dataset = ValidatedDataset(
        projects=[project("P1", "2026-04-01", "completed", 2)], data_issues=[warning]
    )
    result = calculate_metrics(dataset, request())
    assert result.status == "ok"
    assert result.data_issues == [warning]
    assert values(result)["completion_rate"] == 1


def test_only_achievements_keeps_ok_status_but_rate_is_null():
    dataset = ValidatedDataset(
        achievements=[
            Achievement(
                achievement_id="A1",
                department="研发部",
                date="2026-04-01",
                type="模拟交付",
                description="模拟成果",
                source=SourceRef(source_id="achievements.csv", line_number=2),
            )
        ]
    )
    result = calculate_metrics(dataset, request())
    assert result.status == "ok"
    assert values(result)["completion_rate"] is None
    assert values(result)["achievement_count"] == 1
    assert [issue.code for issue in result.data_issues] == ["no_projects"]


def test_completely_empty_dataset_has_no_data_and_null_rate():
    result = calculate_metrics(ValidatedDataset(), request())
    assert result.status == "no_data"
    assert values(result) == {
        "project_count": 0,
        "completed_project_count": 0,
        "completion_rate": None,
        "achievement_count": 0,
    }
    assert [issue.code for issue in result.data_issues] == ["no_projects"]


@pytest.mark.parametrize(
    "start,end",
    [
        ("2026-4-01", "2026-07-01"),
        ("2026-04-31", "2026-07-01"),
        ("2026-04-01T00:00:00", "2026-07-01"),
        (True, "2026-07-01"),
        (datetime(2026, 4, 1), "2026-07-01"),
        ("2026-04-01", "2026-04-01"),
        ("2026-07-01", "2026-04-01"),
    ],
)
def test_data_request_rejects_bad_or_unordered_dates(start, end):
    with pytest.raises(ValidationError):
        request(start=start, end=end)


def test_each_result_has_a_distinct_run_id():
    dataset = ValidatedDataset()
    first = calculate_metrics(dataset, request())
    second = calculate_metrics(dataset, request())
    assert first.run_id != second.run_id
    assert first.created_at
