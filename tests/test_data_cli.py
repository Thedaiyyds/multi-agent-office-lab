"""Offline CLI acceptance checks, including absence of model/config access."""

import json
from pathlib import Path

import pytest

from office_agents.cli import main


@pytest.fixture(autouse=True)
def forbid_model_access(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("data-check must not access model configuration or network")

    monkeypatch.setattr("office_agents.cli.Settings.from_env", forbidden)
    monkeypatch.setattr("office_agents.cli.run_live_smoke", forbidden)
    monkeypatch.setattr("httpx.Client.send", forbidden)


def command(output, *extra):
    return [
        "data-check",
        "--department",
        "研发部",
        "--start-date",
        "2026-04-01",
        "--end-date",
        "2026-07-01",
        "--output-dir",
        str(output),
        *extra,
    ]


def load_report(output):
    paths = list(output.glob("data-*.json"))
    assert len(paths) == 1
    result = json.loads(paths[0].read_text(encoding="utf-8"))
    assert paths[0].name == f"data-{result['run_id']}.json"
    return result


def test_real_samples_saved_with_metrics_and_simulated_origin(tmp_path, capsys):
    assert main(command(tmp_path)) == 0
    output = capsys.readouterr().out
    assert "Mode: offline; status: ok" in output
    assert "unfiltered" in output
    assert "no model request" in output
    result = load_report(tmp_path)
    assert result["request"]["data_origin"] == "simulated"
    assert result["mode"] == "offline"
    metrics = {item["metric_id"]: item["value"] for item in result["metrics"]}
    assert metrics == {
        "project_count": 3,
        "completed_project_count": 2,
        "completion_rate": 2 / 3,
        "achievement_count": 2,
    }
    assert len(result["sources"]) == 3


def test_no_data_is_explicit_and_successful(tmp_path, capsys):
    assert main(command(tmp_path, "--department", "不存在部门")) == 0
    assert "status: no_data" in capsys.readouterr().out
    result = load_report(tmp_path)
    metrics = {item["metric_id"]: item["value"] for item in result["metrics"]}
    assert metrics["completion_rate"] is None
    assert metrics["project_count"] == metrics["achievement_count"] == 0


@pytest.mark.parametrize(
    "extra",
    [
        ["--start-date", "2026-4-1"],
        ["--start-date", "2026-02-30"],
        ["--start-date", "2026-07-01"],
        ["--department", "  "],
    ],
)
def test_invalid_request_never_saves_or_echoes_input(tmp_path, capsys, extra):
    assert main(command(tmp_path, *extra)) == 1
    assert "Invalid data request" in capsys.readouterr().out
    assert list(tmp_path.iterdir()) == []


def test_missing_data_saved_as_invalid_with_no_metrics(tmp_path, capsys):
    output = tmp_path / "reports"
    assert main(command(output, "--data-dir", str(tmp_path / "sensitive-folder"))) == 1
    printed = capsys.readouterr().out
    assert "status: invalid_data" in printed
    assert "sensitive-folder" not in printed
    result = load_report(output)
    assert result["metrics"] == []
    assert result["request"]["data_origin"] == "provided"
    assert str(tmp_path) not in json.dumps(result)


def test_output_failure_returns_safe_failure(tmp_path, capsys):
    occupied = tmp_path / "occupied"
    occupied.write_text("synthetic file", encoding="utf-8")
    assert main(command(occupied)) == 1
    printed = capsys.readouterr().out
    assert "Data report could not be saved" in printed
    assert str(occupied) not in printed


def test_origin_can_be_explicitly_set(tmp_path):
    assert main(command(tmp_path, "--data-origin", "provided")) == 0
    assert load_report(tmp_path)["request"]["data_origin"] == "provided"


def test_default_origin_resolution_handles_symlink_loop_without_traceback(tmp_path, capsys):
    loop = tmp_path / "private-loop"
    loop.symlink_to(Path("private-loop"))
    assert main(command(tmp_path / "reports", "--data-dir", str(loop))) == 1
    output = capsys.readouterr().out
    assert str(loop) not in output
