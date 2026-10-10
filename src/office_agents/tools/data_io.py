"""Bounded file loading and full-dataset validation without model calls."""

import csv
import hashlib
import io
import stat
from pathlib import Path
from threading import RLock

from pydantic import ValidationError

from office_agents.schemas import (
    Achievement,
    DataIssue,
    IssueMaterial,
    ProjectSnapshot,
    RawRow,
    RawTable,
    SourceRecord,
    SourceRef,
    ValidatedDataset,
)

MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_CSV_RECORDS = 10_000
CSV_HEADERS = {
    "projects.csv": (
        "project_id",
        "department",
        "snapshot_date",
        "status",
        "progress",
    ),
    "achievements.csv": (
        "achievement_id",
        "department",
        "date",
        "type",
        "description",
    ),
}
SOURCE_IDS = frozenset((*CSV_HEADERS, "issues.txt"))
_CSV_PARSE_LOCK = RLock()


def _issue(code, message, source_id=None, line_number=None, field=None, severity="error"):
    return DataIssue(
        severity=severity,
        code=code,
        message=message,
        source_id=source_id,
        line_number=line_number,
        field=field,
    )


def _read_bytes(data_root: str | Path, source_id: str):
    """Return bytes or a safe problem; never include paths or input contents."""
    if source_id not in SOURCE_IDS:
        return None, _issue("unknown_source", "Source is not in the fixed file whitelist.")
    try:
        root = Path(data_root).resolve(strict=True)
        if not root.is_dir():
            return None, _issue("invalid_data_root", "Data root must be an existing directory.")
    except (OSError, RuntimeError, ValueError, TypeError):
        return None, _issue("invalid_data_root", "Data root must be an existing directory.")
    try:
        target = (root / source_id).resolve()
        if not target.is_relative_to(root):
            return None, _issue(
                "path_outside_root", "Source resolves outside the authorized directory.", source_id
            )
        metadata = target.stat()
        if not stat.S_ISREG(metadata.st_mode):
            return None, _issue(
                "unreadable_file", "Required source must be a regular file.", source_id
            )
        if metadata.st_size > MAX_FILE_BYTES:
            return None, _issue("file_too_large", "Source exceeds the 2 MiB limit.", source_id)
        with target.open("rb") as stream:
            payload = stream.read(MAX_FILE_BYTES + 1)
        if len(payload) > MAX_FILE_BYTES:
            return None, _issue("file_too_large", "Source exceeds the 2 MiB limit.", source_id)
        return payload, None
    except FileNotFoundError:
        return None, _issue("missing_file", "Required source file is missing.", source_id)
    except (OSError, RuntimeError, ValueError):
        return None, _issue("unreadable_file", "Required source file cannot be read.", source_id)


def _source(source_id: str, payload: bytes, record_count=0):
    return SourceRecord(
        source_id=source_id,
        file_name=source_id,
        sha256=hashlib.sha256(payload).hexdigest(),
        record_count=record_count,
    )


def read_csv(data_root: str | Path, source_id: str) -> RawTable:
    """Read an allowed CSV, retaining original byte hash and physical row starts."""
    if source_id not in CSV_HEADERS:
        return RawTable(
            data_issues=[_issue("unknown_source", "Source is not an allowed CSV file.")]
        )
    payload, problem = _read_bytes(data_root, source_id)
    if problem:
        return RawTable(data_issues=[problem])
    table = RawTable(source=_source(source_id, payload))
    if not payload:
        table.data_issues.append(_issue("empty_csv", "CSV file is empty.", source_id))
        return table
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError:
        table.data_issues.append(
            _issue("invalid_encoding", "Source must contain valid UTF-8 text.", source_id)
        )
        return table
    # A valid bounded file may contain a field larger than csv's 128 KiB default.
    # Use the same bound for a CSV field and the complete input file.
    # The CSV field limit is process-global. Serialize changing/parsing/restoring
    # it when upload validation and independent web sessions run concurrently.
    with _CSV_PARSE_LOCK:
        previous_limit = csv.field_size_limit(MAX_FILE_BYTES)
        try:
            _parse_csv(text, source_id, table)
        finally:
            csv.field_size_limit(previous_limit)
    return table


def _parse_csv(text: str, source_id: str, table: RawTable):
    """Parse within the temporary CSV field-size bound used by read_csv."""
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        headers = next(reader, None)
    except csv.Error:
        table.data_issues.append(_issue("invalid_csv", "CSV syntax is invalid.", source_id, 1))
        return table
    if headers is None:
        table.data_issues.append(_issue("empty_csv", "CSV file has no header.", source_id))
        return table
    valid_headers = len(headers) == len(set(headers)) and set(headers) == set(
        CSV_HEADERS[source_id]
    )
    if not valid_headers:
        table.data_issues.append(
            _issue(
                "invalid_headers",
                "CSV headers must match the required fields exactly.",
                source_id,
                1,
            )
        )
    count = 0
    while True:
        line_number = reader.line_num + 1
        try:
            values = next(reader)
        except StopIteration:
            break
        except csv.Error:
            table.data_issues.append(
                _issue("invalid_csv", "CSV syntax is invalid.", source_id, line_number)
            )
            break
        count += 1
        if count == MAX_CSV_RECORDS + 1:
            table.data_issues.append(
                _issue(
                    "too_many_records",
                    "CSV exceeds the 10,000 record limit.",
                    source_id,
                    line_number,
                )
            )
        if count > MAX_CSV_RECORDS:
            continue
        if len(values) != len(headers):
            table.data_issues.append(
                _issue(
                    "invalid_row_width",
                    "CSV row has an incorrect field count.",
                    source_id,
                    line_number,
                )
            )
            continue
        if valid_headers:
            table.rows.append(
                RawRow(values=dict(zip(headers, values, strict=True)), line_number=line_number)
            )
    table.source.record_count = count
    if count == 0:
        table.data_issues.append(
            _issue("empty_table", "CSV contains no data records.", source_id, severity="warning")
        )
    return table


def _read_issue_material(data_root: str | Path, dataset: ValidatedDataset):
    source_id = "issues.txt"
    payload, problem = _read_bytes(data_root, source_id)
    if problem:
        dataset.data_issues.append(problem)
        return
    # This is a single unfiltered material, not a count of business issues.
    dataset.sources.append(_source(source_id, payload))
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError:
        dataset.data_issues.append(
            _issue("invalid_encoding", "Source must contain valid UTF-8 text.", source_id)
        )
        return
    dataset.issue_materials.append(IssueMaterial(text=text))
    if not text.strip():
        dataset.data_issues.append(
            _issue(
                "empty_issue_material", "Issue material is empty.", source_id, severity="warning"
            )
        )


def _validated_rows(table, model, dataset):
    source_id = table.source.source_id if table.source else None
    for row in table.rows:
        try:
            yield model(
                **row.values, source=SourceRef(source_id=source_id, line_number=row.line_number)
            )
        except ValidationError as exc:
            for error in exc.errors(include_url=False, include_input=False, include_context=False):
                field = str(error["loc"][0]) if error["loc"] else None
                dataset.data_issues.append(
                    _issue(
                        "invalid_project" if model is ProjectSnapshot else "invalid_achievement",
                        "Record violates the required field or consistency rules.",
                        source_id,
                        row.line_number,
                        field,
                    )
                )


def _content(record):
    return record.model_dump(exclude={"source"})


def validate_data(data_root: str | Path) -> ValidatedDataset:
    """Validate all records and global identity constraints before any filtering."""
    dataset = ValidatedDataset()
    tables = {source_id: read_csv(data_root, source_id) for source_id in CSV_HEADERS}
    for table in tables.values():
        if table.source:
            dataset.sources.append(table.source)
        dataset.data_issues.extend(table.data_issues)
    _read_issue_material(data_root, dataset)
    departments = {}
    snapshots = {}
    for record in _validated_rows(tables["projects.csv"], ProjectSnapshot, dataset):
        previous_department = departments.setdefault(record.project_id, record.department)
        if previous_department != record.department:
            dataset.data_issues.append(
                _issue(
                    "project_department_conflict",
                    "Project department must remain unchanged across all snapshots.",
                    record.source.source_id,
                    record.source.line_number,
                    "department",
                )
            )
        key = (record.project_id, record.snapshot_date)
        previous = snapshots.get(key)
        if previous:
            duplicate = _content(previous) == _content(record)
            dataset.data_issues.append(
                _issue(
                    "duplicate_project_snapshot" if duplicate else "project_snapshot_conflict",
                    "Repeated project snapshot was deduplicated."
                    if duplicate
                    else "Project snapshots with the same identity conflict.",
                    record.source.source_id,
                    record.source.line_number,
                    severity="warning" if duplicate else "error",
                )
            )
            continue
        snapshots[key] = record
        dataset.projects.append(record)
    achievements = {}
    for record in _validated_rows(tables["achievements.csv"], Achievement, dataset):
        previous = achievements.get(record.achievement_id)
        if previous:
            duplicate = _content(previous) == _content(record)
            dataset.data_issues.append(
                _issue(
                    "duplicate_achievement" if duplicate else "achievement_conflict",
                    "Repeated achievement was deduplicated."
                    if duplicate
                    else "Achievements with the same identity conflict.",
                    record.source.source_id,
                    record.source.line_number,
                    severity="warning" if duplicate else "error",
                )
            )
            continue
        achievements[record.achievement_id] = record
        dataset.achievements.append(record)
    return dataset
