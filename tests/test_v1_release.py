"""Independent release checks across the public CLI, raw artifacts and packaging."""

import hashlib
import json
import tomllib
from importlib.metadata import version
from pathlib import Path

import httpx
import pytest

from office_agents import __version__
from office_agents.cli import main

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {
    "research-q2": "completed",
    "research-q1": "completed",
    "marketing-q2": "completed",
    "invalid-upload": "input_rejected",
    "missing-request": "needs_input",
    "bad-fact-repair": "completed",
    "persistent-error-limit": "review_failed",
    "model-timeout": "failed",
}


@pytest.fixture
def offline_guard(monkeypatch):
    """A poisoned model environment must be irrelevant to release acceptance."""

    def forbidden(*args, **kwargs):
        raise AssertionError("Acceptance crossed an offline-only boundary.")

    monkeypatch.setenv("LLM_BASE_URL", "https://never-call.invalid")
    monkeypatch.setenv("LLM_MODEL", "DO_NOT_LOAD_MODEL_CONFIG")
    monkeypatch.setenv("LLM_API_KEY", "TEST_SECRET_MUST_NOT_APPEAR")
    monkeypatch.setattr("office_agents.config.Settings.from_env", forbidden)
    monkeypatch.setattr("office_agents.config.load_dotenv", forbidden)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)


def _index_from_cli(output):
    paths = [
        line.removeprefix("Acceptance index: ")
        for line in output.splitlines()
        if line.startswith("Acceptance index: ")
    ]
    assert len(paths) == 1
    index = Path(paths[0])
    return index, json.loads(index.read_text(encoding="utf-8"))


def test_acceptance_cli_matches_actual_artifacts_and_offline_gate(tmp_path, capsys, offline_guard):
    assert main(["acceptance", "--output-dir", str(tmp_path)]) == 0
    console = capsys.readouterr().out
    index, summary = _index_from_cli(console)
    assert summary["passed"] is True and summary["schema_version"] == "1.0"
    assert summary["mode"] == "offline_mock" and summary["external_api_requests"] == 0
    cases = {case["case_id"]: case for case in summary["cases"]}
    assert set(cases) == set(EXPECTED)
    for case_id, expected_status in EXPECTED.items():
        case = cases[case_id]
        assert case["passed"] is True
        assert case["status"] == case["expected_status"] == expected_status
        assert f"PASS {case_id}: {expected_status}" in console
        artifact = (index.parent / case["artifact_dir"]).resolve()
        assert artifact.is_relative_to(index.parent.resolve())
        assert artifact.is_dir()
        if case_id == "invalid-upload":
            assert case["run_id"] is None and case["http_requests"] == 0
            assert not list(artifact.rglob("run.json"))
            assert (artifact / "input-validation.json").is_file()
            assert not list(artifact.rglob("report.md"))
            continue
        result = json.loads((artifact / "run.json").read_text(encoding="utf-8"))
        assert result["mode"] == "offline_mock" and result["status"] == expected_status
        assert case["run_id"] == result["run_id"]
        assert case["http_requests"] == result["request_count"]
        assert case["revision_count"] == result["revision_count"]
        assert case["metrics"] == {m["metric_id"]: m["value"] for m in result["metrics"]}
        assert result["usage"]["total_tokens"] is None
        assert case["http_requests"] <= 10 and case["revision_count"] <= 2
        requests = [e for e in result["events"] if e["event_type"] == "model_request"]
        assert len(requests) == case["http_requests"]
        if expected_status == "completed":
            assert result["review"]["passed"] is True
            assert (artifact / "report.md").read_text(encoding="utf-8").strip()
        else:
            assert not (artifact / "report.md").exists()
    assert cases["research-q2"]["http_requests"] == 6
    assert cases["bad-fact-repair"]["revision_count"] == 1
    assert cases["persistent-error-limit"]["revision_count"] == 2
    assert cases["model-timeout"]["http_requests"] == 1
    serialized = "\n".join(
        p.read_text(encoding="utf-8") for p in index.parent.rglob("*") if p.is_file()
    )
    assert "TEST_SECRET_MUST_NOT_APPEAR" not in serialized + console
    assert "DO_NOT_LOAD_MODEL_CONFIG" not in serialized + console


def test_repeated_cli_acceptance_preserves_first_evidence(tmp_path, capsys, offline_guard):
    command = ["acceptance", "--output-dir", str(tmp_path)]
    assert main(command) == 0
    first_index, first = _index_from_cli(capsys.readouterr().out)
    checksums = {
        p: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in first_index.parent.rglob("*")
        if p.is_file()
    }
    assert main(command) == 0
    second_index, second = _index_from_cli(capsys.readouterr().out)
    assert first["suite_id"] != second["suite_id"]
    assert first_index.parent != second_index.parent
    assert all(hashlib.sha256(p.read_bytes()).hexdigest() == h for p, h in checksums.items())
    first_runs = {c["run_id"] for c in first["cases"] if c["run_id"] is not None}
    second_runs = {c["run_id"] for c in second["cases"] if c["run_id"] is not None}
    assert first_runs.isdisjoint(second_runs)


def test_cli_failed_acceptance_returns_nonzero_and_labels_failure(tmp_path, monkeypatch, capsys):
    from office_agents import acceptance
    from office_agents.web_schemas import PreparedInput, UploadBlob

    original = acceptance.prepare_input

    def changed(files=(), **kwargs):
        prepared = original(files, **kwargs)
        if not kwargs.get("use_samples"):
            return prepared
        return PreparedInput(
            tuple(
                UploadBlob(
                    blob.name,
                    blob.content.replace(b"2026-06-30,active,75", b"2026-06-30,completed,100"),
                )
                if blob.name == "projects.csv"
                else blob
                for blob in prepared.files
            ),
            "simulated",
        )

    monkeypatch.setattr(acceptance, "prepare_input", changed)
    assert main(["acceptance", "--output-dir", str(tmp_path)]) == 1
    output = capsys.readouterr().out
    index, summary = _index_from_cli(output)
    case = next(c for c in summary["cases"] if c["case_id"] == "research-q2")
    # A completed business report does not make a changed baseline acceptance pass.
    assert case["status"] == "completed" and case["passed"] is False
    assert summary["passed"] is False and "hand_calculated_metrics" in case["diagnostics"]
    assert case["metrics"]["completed_project_count"] == 3
    result = json.loads((index.parent / case["artifact_dir"] / "run.json").read_text("utf-8"))
    assert result["status"] == "completed" and result["review"]["passed"] is True
    assert "FAIL research-q2: completed" in output


def test_cli_acceptance_operational_error_is_safe(tmp_path, monkeypatch, capsys):
    def failure(*args, **kwargs):
        raise OSError("PRIVATE_PATH_OR_PROVIDER_BODY")

    monkeypatch.setattr("office_agents.acceptance.run_acceptance", failure)
    assert main(["acceptance", "--output-dir", str(tmp_path)]) == 1
    output = capsys.readouterr().out
    assert "could not complete" in output
    assert "PRIVATE_PATH_OR_PROVIDER_BODY" not in output
    assert not list(tmp_path.rglob("report.md"))


def test_release_version_agrees_with_installed_package():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["version"] == __version__ == version("multi-agent-office-lab")
    assert __version__ == "1.0.0"
