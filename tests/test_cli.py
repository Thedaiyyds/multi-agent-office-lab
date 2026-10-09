"""CLI exit status and diagnostics are checked without contacting a provider."""

import json

import pytest

from office_agents.cli import main
from office_agents.config import Settings
from office_agents.probes import ProbeResult, RunReport


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    monkeypatch.setattr("office_agents.config.load_dotenv", lambda **_: None)
    for name in (
        "LLM_BASE_URL",
        "LLM_MODEL",
        "LLM_API_KEY",
        "LLM_TIMEOUT_SECONDS",
        "LLM_MAX_RETRIES",
    ):
        monkeypatch.delenv(name, raising=False)


def test_doctor_missing_config_fails_locally(capsys):
    assert main(["doctor"]) == 1
    assert "Configuration check failed" in capsys.readouterr().out


def test_doctor_hides_key_and_does_not_claim_live_success(monkeypatch, capsys):
    monkeypatch.setenv("LLM_BASE_URL", "https://model.invalid/v1")
    monkeypatch.setenv("LLM_MODEL", "test")
    monkeypatch.setenv("LLM_API_KEY", "secret-test-key")
    assert main(["doctor"]) == 0
    output = capsys.readouterr().out
    assert "secret-test-key" not in output
    assert "No live request made" in output


def test_smoke_missing_config_saves_failure_and_exits_nonzero(tmp_path, capsys):
    assert main(["smoke", "--output-dir", str(tmp_path)]) == 1
    output = capsys.readouterr().out
    assert "result: failed" in output
    reports = list(tmp_path.glob("live-*.json"))
    assert len(reports) == 1
    assert json.loads(reports[0].read_text())["status"] == "failed"


def test_failed_probe_causes_cli_failure(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("office_agents.cli.Settings.from_env", lambda: Settings())
    monkeypatch.setattr(
        "office_agents.cli.run_live_smoke",
        lambda _, **kwargs: RunReport(
            mode="live",
            status="failed",
            description="Mocked failure, not a live run.",
            probes=[ProbeResult(name="tool_call", passed=False, detail="Unsupported tool call.")],
        ),
    )
    assert main(["smoke", "--output-dir", str(tmp_path)]) == 1
    assert "FAIL tool_call" in capsys.readouterr().out


@pytest.mark.parametrize("profile", ["generic", "deepseek"])
def test_cli_forwards_profile_and_marks_missing_usage_unavailable(
    monkeypatch, tmp_path, capsys, profile
):
    received = []
    monkeypatch.setattr("office_agents.cli.Settings.from_env", lambda: Settings())

    def fake_smoke(settings, **kwargs):
        received.append(kwargs)
        return RunReport(
            mode="live",
            status="failed",
            description="Mocked CLI probe; no real model call.",
            probes=[ProbeResult(name="text", passed=False, detail="Mocked failure.")],
            profile=kwargs["profile"],
            max_output_tokens=64,
            request_count=1,
            usage={"prompt_tokens": None, "completion_tokens": None, "total_tokens": None},
        )

    monkeypatch.setattr("office_agents.cli.run_live_smoke", fake_smoke)
    assert main(["smoke", "--profile", profile, "--output-dir", str(tmp_path)]) == 1
    assert received == [{"profile": profile}]
    output = capsys.readouterr().out
    assert f"Profile: {profile}" in output
    assert "total_tokens: unavailable" in output


def test_graph_demo_success_remains_offline(tmp_path, capsys):
    assert main(["graph-demo", "--output-dir", str(tmp_path)]) == 0
    output = capsys.readouterr().out
    assert "Mode: offline; result: passed" in output
    assert len(list(tmp_path.glob("offline-*.json"))) == 1


def test_failure_to_save_report_exits_nonzero(tmp_path, capsys):
    file_path = tmp_path / "file-not-directory"
    file_path.write_text("occupied", encoding="utf-8")
    assert main(["graph-demo", "--output-dir", str(file_path)]) == 1
    assert "Report could not be saved" in capsys.readouterr().out
