"""Upload ingress tests with synthetic files and no model or network calls."""

import hashlib
from dataclasses import FrozenInstanceError
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from office_agents.schemas import DataRequest
from office_agents.tools.data_io import MAX_FILE_BYTES, validate_data
from office_agents.tools.metrics import run_data_tools
from office_agents.web_schemas import PreparedInput, UploadBlob
from office_agents.web_uploads import (
    WebInputError,
    prepare_input,
    validate_prepared,
    write_prepared,
)

PROJECT_HEADER = "project_id,department,snapshot_date,status,progress\n"
ACHIEVEMENT_HEADER = "achievement_id,department,date,type,description\n"


def files(*, project_rows=None, issues=b"", encoding="utf-8"):
    rows = project_rows or "P1,研发部,2026-04-01,completed,100\n"
    return (
        UploadBlob("projects.csv", (PROJECT_HEADER + rows).encode(encoding)),
        UploadBlob(
            "achievements.csv",
            (ACHIEVEMENT_HEADER + "A1,研发部,2026-04-01,文档,测试手册\n").encode(encoding),
        ),
        UploadBlob("issues.txt", issues),
    )


def replace_file(name, payload):
    return tuple(
        UploadBlob(blob.name, payload if blob.name == name else blob.content) for blob in files()
    )


def codes(exc):
    return {issue.code for issue in exc.value.issues}


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig"])
def test_freezes_order_and_preserves_bytes_and_source_hashes(tmp_path, encoding):
    original = files(encoding=encoding)
    prepared = prepare_input(reversed(original))
    assert prepared.files == original
    assert prepared.data_origin == "provided"
    with pytest.raises(FrozenInstanceError):
        prepared.files = ()
    write_prepared(prepared, tmp_path)
    dataset = validate_data(tmp_path)
    assert not any(issue.severity == "error" for issue in dataset.data_issues)
    hashes = {source.source_id: source.sha256 for source in dataset.sources}
    assert hashes == {blob.name: hashlib.sha256(blob.content).hexdigest() for blob in original}


def test_uploaded_new_data_changes_authoritative_statistics(tmp_path):
    new_files = files(
        project_rows="P1,研发部,2026-04-01,completed,100\nP2,研发部,2026-05-01,active,50\n"
    )
    write_prepared(prepare_input(new_files), tmp_path)
    result = run_data_tools(
        tmp_path,
        DataRequest(department="研发部", start_date="2026-04-01", end_date="2026-07-01"),
    )
    assert {metric.metric_id: metric.value for metric in result.metrics} == {
        "project_count": 2,
        "completed_project_count": 1,
        "completion_rate": 0.5,
        "achievement_count": 1,
    }


def test_samples_frozen_at_acceptance_even_if_source_later_changes(tmp_path):
    for blob in files():
        (tmp_path / blob.name).write_bytes(blob.content)
    prepared = prepare_input(use_samples=True, sample_dir=tmp_path)
    assert prepared.data_origin == "simulated"
    (tmp_path / "projects.csv").write_bytes(b"changed after admission")
    assert prepared.files == files()


@pytest.mark.parametrize(
    "name",
    [
        "../projects.csv",
        "/tmp/projects.csv",
        "projects.csv/x",
        "\\projects.csv",
        "unknown.csv",
        "Projects.csv",
        "projects.csv\x00",
    ],
)
def test_rejects_untrusted_names_without_echoing_them(name):
    with pytest.raises(WebInputError) as exc:
        prepare_input((UploadBlob(name, b"PRIVATE CONTENT"), *files()[1:]))
    assert codes(exc) == {"unknown_source"}
    combined = str(exc.value) + repr(exc.value.issues)
    assert name not in combined
    assert "PRIVATE CONTENT" not in combined


@pytest.mark.parametrize(
    "content", ["private content", bytearray(b"data"), memoryview(b"data"), None]
)
def test_rejects_nonimmutable_bytes(content):
    with pytest.raises(WebInputError) as exc:
        prepare_input(replace_file("issues.txt", content))
    assert codes(exc) == {"invalid_bytes"}


def test_rejects_duplicate_missing_and_excess_files():
    with pytest.raises(WebInputError) as exc:
        prepare_input((files()[0], files()[0], files()[2]))
    assert codes(exc) == {"duplicate_file"}
    with pytest.raises(WebInputError) as exc:
        prepare_input(files()[:1])
    assert codes(exc) == {"missing_file"}
    assert {issue.source_id for issue in exc.value.issues} == {"achievements.csv", "issues.txt"}
    with pytest.raises(WebInputError) as exc:
        prepare_input((*files(), files()[0]))
    assert codes(exc) == {"too_many_files"}


def test_empty_text_and_header_only_tables_are_valid_warning_cases():
    prepared = prepare_input(files())
    assert prepared.files[-1].content == b""
    assert (
        prepare_input(replace_file("projects.csv", PROJECT_HEADER.encode())).files[0].content
        == PROJECT_HEADER.encode()
    )


@pytest.mark.parametrize(
    "name,payload,expected",
    [
        ("issues.txt", b"\xffprivate", "invalid_encoding"),
        ("projects.csv", b"", "empty_csv"),
        ("projects.csv", b"secret_header\nPRIVATE\n", "invalid_headers"),
        ("projects.csv", (PROJECT_HEADER + '"unterminated').encode(), "invalid_csv"),
        (
            "projects.csv",
            (PROJECT_HEADER + "P1,研发部,2026-04-01,active\n").encode(),
            "invalid_row_width",
        ),
        (
            "projects.csv",
            (PROJECT_HEADER + "P1,研发部,2026-04-01,completed,30\n").encode(),
            "invalid_project",
        ),
        (
            "achievements.csv",
            (ACHIEVEMENT_HEADER + "A1,研发部,invalid-date,文档,PRIVATE\n").encode(),
            "invalid_achievement",
        ),
    ],
)
def test_reuses_full_parser_and_business_validation(name, payload, expected):
    with pytest.raises(WebInputError) as exc:
        prepare_input(replace_file(name, payload))
    assert expected in codes(exc)
    assert "PRIVATE" not in str(exc.value) + repr(exc.value.issues)
    assert "secret_header" not in repr(exc.value.issues)


def test_file_byte_limit_is_inclusive():
    assert prepare_input(replace_file("issues.txt", b"x" * MAX_FILE_BYTES))
    with pytest.raises(WebInputError) as exc:
        prepare_input(replace_file("issues.txt", b"x" * (MAX_FILE_BYTES + 1)))
    assert codes(exc) == {"file_too_large"}


def test_record_limit_not_bypassed_by_small_files():
    rows = "".join(f"P{i},研发部,2026-04-01,active,50\n" for i in range(10_001))
    with pytest.raises(WebInputError) as exc:
        prepare_input(files(project_rows=rows))
    assert "too_many_records" in codes(exc)


@pytest.mark.parametrize("valid", [True, False])
def test_temporary_files_removed_on_success_and_validation_failure(monkeypatch, valid):
    import office_agents.web_uploads as uploads

    seen = []

    def capture(*args, **kwargs):
        directory = TemporaryDirectory(*args, **kwargs)
        seen.append(Path(directory.name))
        return directory

    monkeypatch.setattr(uploads, "TemporaryDirectory", capture)
    if valid:
        prepare_input(files())
    else:
        with pytest.raises(WebInputError):
            prepare_input(replace_file("issues.txt", b"\xff"))
    assert len(seen) == 1
    assert not seen[0].exists()


def test_storage_and_validator_exceptions_are_safe_and_temporary_is_cleaned(monkeypatch):
    import office_agents.web_uploads as uploads

    seen = []

    def capture(*args, **kwargs):
        directory = TemporaryDirectory(*args, **kwargs)
        seen.append(Path(directory.name))
        return directory

    def broken(_root):
        raise RuntimeError("/private/secret SOURCE CONTENT")

    monkeypatch.setattr(uploads, "TemporaryDirectory", capture)
    monkeypatch.setattr(uploads, "validate_data", broken)
    with pytest.raises(WebInputError) as exc:
        prepare_input(files())
    assert codes(exc) == {"input_validation_failed"}
    assert "secret" not in str(exc.value) + repr(exc.value.issues)
    assert not seen[0].exists()


def test_broken_iterable_is_safe_and_samples_cannot_mix_with_uploads():
    def broken():
        yield files()[0]
        raise RuntimeError("/private/secret")

    with pytest.raises(WebInputError) as exc:
        prepare_input(broken())
    assert codes(exc) == {"invalid_upload"}
    assert "secret" not in str(exc.value)
    for entries in (files(), (None,)):
        with pytest.raises(WebInputError) as exc:
            prepare_input(entries, use_samples=True)
        assert codes(exc) == {"mixed_input_mode"}


def test_manually_constructed_prepared_cannot_bypass_validation(tmp_path):
    with pytest.raises(WebInputError) as exc:
        validate_prepared(PreparedInput(files(), "untrusted"))
    assert codes(exc) == {"invalid_prepared_input"}
    invalid = PreparedInput(replace_file("issues.txt", b"\xff"), "provided")
    with pytest.raises(WebInputError):
        write_prepared(invalid, tmp_path)
    assert not list(tmp_path.iterdir())


def test_samples_symlink_escape_and_missing_data_are_safe(tmp_path):
    with pytest.raises(WebInputError) as exc:
        prepare_input(use_samples=True, sample_dir=tmp_path)
    assert codes(exc) == {"missing_file"}
    outside = tmp_path.parent / "outside-upload-sample.csv"
    outside.write_bytes(files()[0].content)
    (tmp_path / "projects.csv").symlink_to(outside)
    with pytest.raises(WebInputError) as exc:
        prepare_input(use_samples=True, sample_dir=tmp_path)
    assert codes(exc) == {"path_outside_root"}
    assert str(outside) not in str(exc.value) + repr(exc.value.issues)


def test_writer_never_overwrites_existing_or_symlink_files(tmp_path):
    sentinel = tmp_path / "achievements.csv"
    sentinel.write_bytes(b"existing")
    with pytest.raises(WebInputError) as exc:
        write_prepared(prepare_input(files()), tmp_path)
    assert codes(exc) == {"input_storage_failed"}
    assert sentinel.read_bytes() == b"existing"
    assert not (tmp_path / "projects.csv").exists()
    sentinel.unlink()
    outside = tmp_path.parent / "outside-upload-write.csv"
    outside.write_bytes(b"outside")
    (tmp_path / "projects.csv").symlink_to(outside)
    with pytest.raises(WebInputError):
        write_prepared(prepare_input(files()), tmp_path)
    assert outside.read_bytes() == b"outside"
