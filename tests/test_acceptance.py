"""Independent release acceptance boundaries; all runs use local HTTP fixtures."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest

import office_agents.acceptance as acceptance
from office_agents.agent_runtime import AgentSession
from office_agents.config import Settings
from office_agents.schemas import DataIssue
from office_agents.web_schemas import PreparedInput, UploadBlob
from office_agents.web_uploads import WebInputError


def _cases(summary):
    return {case["case_id"]: case for case in summary["cases"]}


def test_eight_real_cases_have_consistent_artifacts_and_hand_calculated_results(tmp_path):
    result, index = acceptance.run_acceptance(tmp_path)
    assert result == json.loads(index.read_text("utf-8"))
    assert result["passed"] is True
    assert result["schema_version"] == "1.0"
    assert result["mode"] == "offline_mock"
    assert result["external_api_requests"] == 0
    assert str(UUID(result["suite_id"])) == index.parent.name
    cases = _cases(result)
    assert len(cases) == 8
    assert cases["research-q2"]["metrics"] == {
        "project_count": 3,
        "completed_project_count": 2,
        "completion_rate": 2 / 3,
        "achievement_count": 2,
    }
    assert cases["research-q1"]["metrics"] == {
        "project_count": 2,
        "completed_project_count": 1,
        "completion_rate": 0.5,
        "achievement_count": 1,
    }
    assert cases["marketing-q2"]["metrics"] == {
        "project_count": 1,
        "completed_project_count": 0,
        "completion_rate": 0,
        "achievement_count": 1,
    }
    assert sum(case["http_requests"] for case in cases.values()) == 34
    for case in cases.values():
        assert case["passed"] is True and not case["diagnostics"]
        directory = index.parent / case["artifact_dir"]
        assert directory.resolve().is_relative_to(index.parent.resolve())
        assert (directory / "report.md").exists() == (case["status"] == "completed")
        if case["run_id"] is None:
            validation = json.loads((directory / "input-validation.json").read_text("utf-8"))
            assert validation["issue_codes"] == ["invalid_headers"]
            assert case["http_requests"] == 0 and case["status"] == "input_rejected"
            continue
        run = json.loads((directory / "run.json").read_text("utf-8"))
        assert run["run_id"] == case["run_id"]
        assert run["status"] == case["status"]
        assert run["request_count"] == case["http_requests"]
        assert run["revision_count"] == case["revision_count"]
    repaired = json.loads(
        (index.parent / cases["bad-fact-repair"]["artifact_dir"] / "run.json").read_text("utf-8")
    )
    stopped = json.loads(
        (index.parent / cases["persistent-error-limit"]["artifact_dir"] / "run.json").read_text(
            "utf-8"
        )
    )
    assert [item["review"]["passed"] for item in repaired["revision_history"]] == [False, True]
    assert [item["review"]["passed"] for item in stopped["revision_history"]] == [False] * 3
    assert stopped["revision_count"] == stopped["max_revisions"] == 2


def test_repeat_runs_preserve_previous_suite_and_never_modify_sample_bytes(tmp_path):
    source = Path("data/samples")
    before = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in source.iterdir()
        if path.is_file()
    }
    first, first_index = acceptance.run_acceptance(tmp_path)
    existing = {
        path.relative_to(first_index.parent): path.read_bytes()
        for path in first_index.parent.rglob("*")
        if path.is_file()
    }
    second, second_index = acceptance.run_acceptance(tmp_path)
    assert first["passed"] and second["passed"]
    assert first_index.parent != second_index.parent
    assert (
        len(
            {
                case["run_id"]
                for summary in (first, second)
                for case in summary["cases"]
                if case["run_id"]
            }
        )
        == 14
    )
    for relative, original in existing.items():
        assert (first_index.parent / relative).read_bytes() == original
    assert before == {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in source.iterdir()
        if path.is_file()
    }


def test_offline_entry_never_loads_environment_or_uses_network_and_closes_sessions(
    tmp_path,
    monkeypatch,
):
    def forbidden(*args, **kwargs):
        raise AssertionError("Environment/network access forbidden")

    monkeypatch.setattr(Settings, "from_env", forbidden)
    monkeypatch.setattr("office_agents.config.load_dotenv", forbidden)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)
    closed = []
    original_close = AgentSession.close

    def track_close(self):
        original_close(self)
        closed.append(self.client._client.is_closed)

    monkeypatch.setattr(AgentSession, "close", track_close)
    monkeypatch.setenv("LLM_API_KEY", "PRIVATE_UNUSED_TEST_SECRET")
    result, index = acceptance.run_acceptance(tmp_path)
    assert result["passed"] is True
    assert closed == [True] * 7
    for path in index.parent.rglob("*"):
        if path.is_file():
            assert b"PRIVATE_UNUSED_TEST_SECRET" not in path.read_bytes()


def test_actual_changed_input_cannot_pass_original_hand_calculation(tmp_path, monkeypatch):
    original = acceptance.prepare_input

    def changed(files=(), **kwargs):
        prepared = original(files, **kwargs)
        if kwargs.get("use_samples"):
            return PreparedInput(
                tuple(
                    UploadBlob(blob.name, blob.content.replace(b"active,75", b"completed,100"))
                    if blob.name == "projects.csv"
                    else blob
                    for blob in prepared.files
                ),
                "simulated",
            )
        return prepared

    monkeypatch.setattr(acceptance, "prepare_input", changed)
    result, _ = acceptance.run_acceptance(tmp_path)
    assert result["passed"] is False
    research = _cases(result)["research-q2"]
    assert research["status"] == "completed"
    assert research["metrics"]["completed_project_count"] == 3
    assert research["metrics"]["completion_rate"] == 1
    assert "hand_calculated_metrics" in research["diagnostics"]


def test_missing_field_admission_regression_is_failure(tmp_path, monkeypatch):
    original = acceptance.prepare_input

    def admits_bad(files=(), **kwargs):
        if not kwargs.get("use_samples"):
            return object()
        return original(files, **kwargs)

    monkeypatch.setattr(acceptance, "prepare_input", admits_bad)
    result, _ = acceptance.run_acceptance(tmp_path)
    rejected = _cases(result)["invalid-upload"]
    assert not result["passed"] and not rejected["passed"]
    assert rejected["status"] == "input_accepted"
    assert rejected["diagnostics"] == ["invalid_upload_was_admitted"]


def test_wrong_upload_error_does_not_count_as_expected_rejection(tmp_path, monkeypatch):
    original = acceptance.prepare_input

    def wrong_error(files=(), **kwargs):
        if not kwargs.get("use_samples"):
            raise WebInputError([DataIssue(severity="error", code="missing_file", message="safe")])
        return original(files, **kwargs)

    monkeypatch.setattr(acceptance, "prepare_input", wrong_error)
    result, _ = acceptance.run_acceptance(tmp_path)
    rejected = _cases(result)["invalid-upload"]
    assert not result["passed"] and not rejected["passed"]
    assert rejected["status"] == "input_rejected"
    assert rejected["diagnostics"] == ["unexpected_input_rejection"]


def test_unexpected_graph_exception_is_not_a_passing_timeout_and_is_safe(tmp_path, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("PRIVATE_PATH_AND_PROVIDER_SECRET")

    monkeypatch.setattr(acceptance, "run_workflow", broken)
    result, index = acceptance.run_acceptance(tmp_path)
    cases = _cases(result)
    assert result["passed"] is False
    assert cases["model-timeout"]["status"] == "failed"
    assert cases["model-timeout"]["passed"] is False
    assert cases["model-timeout"]["http_requests"] == 0
    assert "PRIVATE_PATH_AND_PROVIDER_SECRET" not in index.read_text("utf-8")


def test_export_failure_is_not_success_and_every_session_is_closed(tmp_path, monkeypatch):
    def broken(*args, **kwargs):
        raise OSError("PRIVATE_EXPORT_PATH")

    closed = []
    original_close = AgentSession.close

    def close(self):
        original_close(self)
        closed.append(True)

    monkeypatch.setattr(AgentSession, "close", close)
    monkeypatch.setattr(acceptance, "save_workflow", broken)
    result, index = acceptance.run_acceptance(tmp_path)
    assert result["passed"] is False
    assert not _cases(result)["research-q2"]["passed"]
    assert closed == [True] * 7
    assert "PRIVATE_EXPORT_PATH" not in index.read_text("utf-8")


def test_missing_final_export_cannot_pass_completed_status(tmp_path, monkeypatch):
    original = acceptance.save_workflow

    def missing_final(result, output_root):
        directory = original(result, output_root)
        (directory / "report.md").unlink(missing_ok=True)
        return directory

    monkeypatch.setattr(acceptance, "save_workflow", missing_final)
    result, _ = acceptance.run_acceptance(tmp_path)
    case = _cases(result)["research-q2"]
    assert case["status"] == "completed"
    assert not result["passed"] and not case["passed"]
    assert "final_report_gate" in case["diagnostics"]


def test_corrupted_saved_audit_cannot_pass_expected_stopped_status(tmp_path, monkeypatch):
    original = acceptance.save_workflow

    def bad_audit(result, output_root):
        directory = original(result, output_root)
        if result.status == "failed":
            (directory / "events.jsonl").write_text("", encoding="utf-8")
        return directory

    monkeypatch.setattr(acceptance, "save_workflow", bad_audit)
    result, _ = acceptance.run_acceptance(tmp_path)
    case = _cases(result)["model-timeout"]
    assert case["status"] == "failed"
    assert not result["passed"] and not case["passed"]
    assert "saved_events_match" in case["diagnostics"]


def test_unique_suite_collision_refuses_overwrite(tmp_path, monkeypatch):
    fixed = UUID("11111111-1111-4111-8111-111111111111")
    old = tmp_path / str(fixed)
    old.mkdir()
    marker = old / "summary.json"
    marker.write_text("old suite", encoding="utf-8")
    monkeypatch.setattr(acceptance, "uuid4", lambda: fixed)
    with pytest.raises(acceptance.AcceptanceError, match="could not be created"):
        acceptance.run_acceptance(tmp_path)
    assert marker.read_text("utf-8") == "old suite"


def test_output_file_and_symlink_are_rejected_with_safe_errors(tmp_path):
    existing = tmp_path / "private-output-file"
    existing.write_text("original", encoding="utf-8")
    link = tmp_path / "private-output-link"
    link.symlink_to(tmp_path, target_is_directory=True)
    for destination in (existing, link):
        with pytest.raises(acceptance.AcceptanceError) as error:
            acceptance.run_acceptance(destination)
        assert "private-output" not in str(error.value)
    assert existing.read_text("utf-8") == "original"


def test_git_failure_returns_null_commit_without_environment_or_exception_text(
    tmp_path, monkeypatch
):
    def failure(*args, **kwargs):
        raise OSError("PRIVATE_GIT_ENV")

    monkeypatch.setattr(acceptance.subprocess, "run", failure)
    result, index = acceptance.run_acceptance(tmp_path)
    assert result["passed"] is True and result["source_commit"] is None
    assert result["source_dirty"] is None
    assert "PRIVATE_GIT_ENV" not in index.read_text("utf-8")


def test_git_dirty_metadata_keeps_only_boolean_and_commit_not_private_paths(tmp_path, monkeypatch):
    def probe(args, **kwargs):
        if args[1] == "rev-parse":
            return SimpleNamespace(returncode=0, stdout="a" * 40 + "\n")
        assert args == ["git", "status", "--porcelain", "--untracked-files=normal"]
        return SimpleNamespace(returncode=0, stdout=" M PRIVATE_UNTRACKED_DATA_FILENAME\n")

    monkeypatch.setattr(acceptance.subprocess, "run", probe)
    result, index = acceptance.run_acceptance(tmp_path)
    assert result["passed"] is True
    assert result["source_commit"] == "a" * 40
    assert result["source_dirty"] is True
    assert "PRIVATE_UNTRACKED_DATA_FILENAME" not in index.read_text("utf-8")


def test_index_write_failure_returns_safe_error(tmp_path, monkeypatch):
    original = acceptance._json_write

    def failed_index(path, value):
        if path.name == "summary.json":
            raise OSError("PRIVATE_INDEX_PATH")
        original(path, value)

    monkeypatch.setattr(acceptance, "_json_write", failed_index)
    with pytest.raises(acceptance.AcceptanceError) as error:
        acceptance.run_acceptance(tmp_path)
    assert str(error.value) == "Acceptance summary could not be saved."
