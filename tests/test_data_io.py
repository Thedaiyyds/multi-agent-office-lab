"""Independent malformed-file and provenance checks; all fixtures are synthetic."""

import csv
import hashlib
from pathlib import Path

import pytest

from office_agents.tools.data_io import read_csv, validate_data

PROJECT_HEADER = "project_id,department,snapshot_date,status,progress\n"
PROJECT_ROW = "P1,研发部,2026-04-01,active,40\n"
ACHIEVEMENT_HEADER = "achievement_id,department,date,type,description\n"
ACHIEVEMENT_ROW = "A1,研发部,2026-04-01,文档,操作手册\n"


@pytest.fixture
def data_root(tmp_path):
    (tmp_path / "projects.csv").write_text(PROJECT_HEADER + PROJECT_ROW, encoding="utf-8")
    (tmp_path / "achievements.csv").write_text(
        ACHIEVEMENT_HEADER + ACHIEVEMENT_ROW, encoding="utf-8"
    )
    (tmp_path / "issues.txt").write_text("  市场部历史问题，日期未标注。\n", encoding="utf-8")
    return tmp_path


def codes(result):
    return {issue.code for issue in result.data_issues}


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig"])
def test_csv_accepts_utf8_and_bom_and_hashes_original_bytes(data_root, encoding):
    path = data_root / "projects.csv"
    path.write_text(PROJECT_HEADER + PROJECT_ROW, encoding=encoding)
    table = read_csv(data_root, "projects.csv")
    assert table.data_issues == []
    assert table.rows[0].values["department"] == "研发部"
    assert table.rows[0].line_number == 2
    assert table.source.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert table.source.record_count == 1
    assert table.source.file_name == "projects.csv"
    assert str(data_root) not in table.model_dump_json()


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (b"", "empty_csv"),
        (b"\xff\xfe", "invalid_encoding"),
        (b"project_id,department\nP1,secret-row-content\n", "invalid_headers"),
        ((PROJECT_HEADER.rstrip() + ",progress\n" + PROJECT_ROW).encode(), "invalid_headers"),
        ((PROJECT_HEADER.rstrip() + ",secret-extra\n" + PROJECT_ROW).encode(), "invalid_headers"),
        ((PROJECT_HEADER + "P1,secret-row-content\n").encode(), "invalid_row_width"),
        ((PROJECT_HEADER + '"unterminated,secret-row-content\n').encode(), "invalid_csv"),
    ],
)
def test_bad_csv_has_safe_structured_errors(data_root, content, expected):
    (data_root / "projects.csv").write_bytes(content)
    result = read_csv(data_root, "projects.csv")
    assert expected in codes(result)
    summaries = " ".join(issue.message for issue in result.data_issues)
    assert "secret-row-content" not in summaries
    assert "secret-extra" not in summaries
    assert str(data_root) not in summaries


def test_header_only_is_warning_with_zero_records(data_root):
    (data_root / "projects.csv").write_text(PROJECT_HEADER, encoding="utf-8")
    table = read_csv(data_root, "projects.csv")
    assert codes(table) == {"empty_table"}
    assert table.source.record_count == 0
    assert table.rows == []
    assert all(issue.severity == "warning" for issue in table.data_issues)


def test_columns_can_be_reordered(data_root):
    (data_root / "projects.csv").write_text(
        "progress,status,snapshot_date,department,project_id\n40,active,2026-04-01,研发部,P1\n",
        encoding="utf-8",
    )
    dataset = validate_data(data_root)
    assert dataset.data_issues == []
    assert dataset.projects[0].project_id == "P1"


def test_quoted_multiline_fields_keep_physical_start_line_and_text(data_root):
    (data_root / "achievements.csv").write_text(
        ACHIEVEMENT_HEADER
        + 'A1,研发部,2026-04-01,文档,"首行\n第二行"\n'
        + "A2,研发部,2026-04-02,文档,后续记录\n",
        encoding="utf-8",
    )
    table = read_csv(data_root, "achievements.csv")
    assert [row.line_number for row in table.rows] == [2, 4]
    assert table.rows[0].values["description"] == "首行\n第二行"
    dataset = validate_data(data_root)
    assert [item.source.line_number for item in dataset.achievements] == [2, 4]


@pytest.mark.parametrize(
    "row",
    [
        "P1,研发部,2026-02-30,active,40\n",
        "P1,研发部,2026-4-01,active,40\n",
        "P1,研发部,2026-04-01,active,NaN\n",
        "P1,研发部,2026-04-01,active,inf\n",
        "P1,研发部,2026-04-01,active,-1\n",
        "P1,研发部,2026-04-01,active,101\n",
        "P1,研发部,2026-04-01,completed,99\n",
        "P1,研发部,2026-04-01,unknown,40\n",
    ],
)
def test_project_rejects_invalid_semantics(data_root, row):
    (data_root / "projects.csv").write_text(PROJECT_HEADER + row, encoding="utf-8")
    result = validate_data(data_root)
    assert "invalid_project" in codes(result)
    assert result.projects == []
    issue = next(issue for issue in result.data_issues if issue.code == "invalid_project")
    assert issue.source_id == "projects.csv"
    assert issue.line_number == 2
    assert issue.severity == "error"


def test_project_same_day_duplicates_are_deduplicated_and_counted_in_source(data_root):
    (data_root / "projects.csv").write_text(PROJECT_HEADER + PROJECT_ROW * 2, encoding="utf-8")
    result = validate_data(data_root)
    assert len(result.projects) == 1
    assert codes(result) == {"duplicate_project_snapshot"}
    assert (
        next(source for source in result.sources if source.source_id == "projects.csv").record_count
        == 2
    )
    issue = result.data_issues[0]
    assert issue.severity == "warning" and issue.line_number == 3


@pytest.mark.parametrize(
    ("second", "expected"),
    [
        ("P1,研发部,2026-04-01,active,50\n", "project_snapshot_conflict"),
        ("P1,市场部,2026-04-02,active,40\n", "project_department_conflict"),
    ],
)
def test_project_conflicts_are_not_silently_selected(data_root, second, expected):
    (data_root / "projects.csv").write_text(PROJECT_HEADER + PROJECT_ROW + second, encoding="utf-8")
    assert expected in codes(validate_data(data_root))


@pytest.mark.parametrize(
    ("second", "expected", "severity"),
    [
        (ACHIEVEMENT_ROW, "duplicate_achievement", "warning"),
        ("A1,研发部,2026-04-02,文档,另一份手册\n", "achievement_conflict", "error"),
    ],
)
def test_achievement_ids_have_global_uniqueness(data_root, second, expected, severity):
    (data_root / "achievements.csv").write_text(
        ACHIEVEMENT_HEADER + ACHIEVEMENT_ROW + second, encoding="utf-8"
    )
    result = validate_data(data_root)
    issue = next(issue for issue in result.data_issues if issue.code == expected)
    assert issue.severity == severity
    if severity == "warning":
        assert len(result.achievements) == 1


def test_achievement_invalid_date_and_empty_description_are_reported(data_root):
    (data_root / "achievements.csv").write_text(
        ACHIEVEMENT_HEADER + "A1,研发部,2026-02-30,文档,\n", encoding="utf-8"
    )
    result = validate_data(data_root)
    assert "invalid_achievement" in codes(result)
    assert result.achievements == []


def test_issue_text_is_unfiltered_preserved_and_not_counted(data_root):
    result = validate_data(data_root)
    assert result.issue_materials[0].scope == "unfiltered"
    assert result.issue_materials[0].text == "  市场部历史问题，日期未标注。\n"
    source = next(source for source in result.sources if source.source_id == "issues.txt")
    assert source.record_count == 0


def test_empty_issues_allowed_with_warning(data_root):
    (data_root / "issues.txt").write_text("", encoding="utf-8")
    result = validate_data(data_root)
    assert codes(result) == {"empty_issue_material"}
    assert result.data_issues[0].severity == "warning"


@pytest.mark.parametrize("name", ["projects.csv", "achievements.csv", "issues.txt"])
def test_missing_required_files_are_errors(data_root, name):
    (data_root / name).unlink()
    result = validate_data(data_root)
    issue = next(issue for issue in result.data_issues if issue.code == "missing_file")
    assert issue.source_id == name
    assert str(data_root) not in issue.message


def test_file_size_and_csv_record_limits_are_distinct(data_root):
    (data_root / "projects.csv").write_bytes(b"x" * (2 * 1024 * 1024 + 1))
    oversized = read_csv(data_root, "projects.csv")
    assert codes(oversized) == {"file_too_large"}
    assert oversized.source is None
    (data_root / "projects.csv").write_text(PROJECT_HEADER + PROJECT_ROW * 10_001, encoding="utf-8")
    too_many = read_csv(data_root, "projects.csv")
    assert "too_many_records" in codes(too_many)
    assert too_many.source.record_count == 10_001
    assert len(too_many.rows) <= 10_000
    (data_root / "projects.csv").write_text(PROJECT_HEADER + PROJECT_ROW * 10_000, encoding="utf-8")
    assert "too_many_records" not in codes(read_csv(data_root, "projects.csv"))


@pytest.mark.parametrize("source_id", ["../outside.csv", "secret.csv", "/tmp/projects.csv"])
def test_source_whitelist_rejects_arbitrary_paths(data_root, source_id):
    result = read_csv(data_root, source_id)
    assert codes(result) == {"unknown_source"}
    assert source_id not in " ".join(issue.message for issue in result.data_issues)


def test_symlink_cannot_escape_authorized_root(data_root, tmp_path):
    outside = tmp_path.parent / f"{tmp_path.name}-outside.csv"
    outside.write_text(PROJECT_HEADER + PROJECT_ROW, encoding="utf-8")
    path = data_root / "projects.csv"
    path.unlink()
    path.symlink_to(outside)
    result = read_csv(data_root, "projects.csv")
    assert codes(result) == {"path_outside_root"}
    assert result.source is None and result.rows == []
    assert str(outside) not in result.model_dump_json()


def test_source_symlink_loop_is_safe_error(data_root):
    path = data_root / "projects.csv"
    path.unlink()
    path.symlink_to(Path("projects.csv"))
    result = read_csv(data_root, "projects.csv")
    assert any(issue.severity == "error" for issue in result.data_issues)
    assert str(data_root) not in result.model_dump_json()


def test_long_field_under_file_limit_is_valid_and_restores_csv_setting(data_root):
    previous_limit = csv.field_size_limit()
    description = "x" * 150_000
    (data_root / "achievements.csv").write_text(
        ACHIEVEMENT_HEADER + f"A1,研发部,2026-04-01,文档,{description}\n", encoding="utf-8"
    )
    table = read_csv(data_root, "achievements.csv")
    assert table.data_issues == []
    assert table.rows[0].values["description"] == description
    assert csv.field_size_limit() == previous_limit
    (data_root / "achievements.csv").write_text(
        ACHIEVEMENT_HEADER + '"unterminated', encoding="utf-8"
    )
    assert "invalid_csv" in codes(read_csv(data_root, "achievements.csv"))
    assert csv.field_size_limit() == previous_limit


def test_invalid_issue_encoding_is_reported_with_original_hash(data_root):
    payload = b"\xffprivate-issue-text"
    (data_root / "issues.txt").write_bytes(payload)
    result = validate_data(data_root)
    issue = next(issue for issue in result.data_issues if issue.code == "invalid_encoding")
    assert issue.source_id == "issues.txt"
    assert "private-issue-text" not in issue.message
    assert result.issue_materials == []
    source = next(source for source in result.sources if source.source_id == "issues.txt")
    assert source.sha256 == hashlib.sha256(payload).hexdigest()
