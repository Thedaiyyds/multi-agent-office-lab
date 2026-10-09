"""Independent role command acceptance, with model configuration forbidden in mock mode."""

import json

import pytest

from office_agents.agent_examples import sample_content, sample_outline, sample_requirements
from office_agents.cli import main
from office_agents.schemas import DataRequest
from office_agents.tools.metrics import run_data_tools


@pytest.fixture(autouse=True)
def no_live_configuration(monkeypatch):
    def forbidden():
        raise AssertionError("Mock examples must not load credentials.")

    monkeypatch.setattr("office_agents.cli.Settings.from_env", forbidden)


def command(tmp_path, *extra):
    return ["agent-demo", "--output-dir", str(tmp_path), *extra]


def report(tmp_path):
    files = list(tmp_path.glob("agents-*.json"))
    assert len(files) == 1
    return json.loads(files[0].read_text())


def test_default_examples_are_explicit_mock_with_real_tool_execution(tmp_path, capsys):
    assert main(command(tmp_path)) == 0
    result = report(tmp_path)
    assert result["mode"] == "offline_mock" and result["request_count"] == 6
    assert result["reserved_output_tokens"] == 1984
    assert [item["role"] for item in result["runs"]] == [
        "manager",
        "planner",
        "data",
        "writer",
        "checker",
    ]
    assert all(item["status"] == "passed" for item in result["runs"])
    tools = [event for event in result["events"] if event["event_type"] == "tool_execution"]
    assert len(tools) == 1 and tools[0]["tool_name"] == "run_data_tools"
    assert result["usage"]["total_tokens"] is None
    assert "no real model requests" in capsys.readouterr().out


def test_bad_draft_is_rejected_despite_scripted_model_approval(tmp_path):
    assert main(command(tmp_path, "--role", "checker", "--case", "bad-draft")) == 1
    result = report(tmp_path)
    assert result["status"] == "review_failed"
    assert result["request_count"] == 1
    review = result["runs"][0]["output"]
    assert not review["passed"]
    codes = {issue["code"] for issue in review["issues"]}
    assert {"fact_value", "required_sections"} <= codes


def test_missing_requirements_are_explicit(tmp_path):
    assert main(command(tmp_path, "--role", "manager", "--case", "missing-requirements")) == 1
    result = report(tmp_path)
    assert result["status"] == "needs_input"
    assert result["runs"][0]["output"]["requirements"] is None


@pytest.mark.parametrize("role", ["manager", "planner"])
def test_parsing_roles_do_not_read_data_files(tmp_path, monkeypatch, role):
    def forbidden(*args, **kwargs):
        raise AssertionError("Parsing roles must be independent of local data.")

    monkeypatch.setattr("office_agents.agent_examples.run_data_tools", forbidden)
    assert main(command(tmp_path, "--role", role, "--data-dir", str(tmp_path / "absent"))) == 0


def test_budget_exhaustion_stops_all_examples(tmp_path):
    assert main(command(tmp_path, "--max-requests", "1")) == 1
    result = report(tmp_path)
    assert result["request_count"] == 1
    assert len(result["runs"]) == 2 and result["runs"][-1]["status"] == "failed"


def test_invalid_request_does_not_echo_values(tmp_path, capsys):
    assert main(command(tmp_path, "--start-date", "private-bad-value")) == 1
    assert "private-bad-value" not in capsys.readouterr().out
    assert not list(tmp_path.glob("agents-*.json"))


def test_save_failure_is_static(tmp_path, capsys):
    occupied = tmp_path / "private-file"
    occupied.write_text("occupied")
    assert main(command(occupied, "--role", "manager")) == 1
    output = capsys.readouterr().out
    assert "report could not be saved" in output and "private-file" not in output


def test_fixture_provenance_does_not_mislabel_provided_data():
    req = sample_requirements(data_origin="provided")
    data = run_data_tools(
        "data/samples",
        DataRequest(
            department=req.department,
            start_date=req.start_date,
            end_date=req.end_date,
            data_origin="provided",
        ),
    )
    content = sample_content(sample_outline(req), data)
    assert all("模拟统计" not in section.text for section in content.sections)


def test_empty_fixture_does_not_generate_claims(tmp_path):
    assert main(command(tmp_path, "--role", "writer", "--department", "财务部")) == 1
    result = report(tmp_path)
    assert result["request_count"] == 0 and result["status"] == "needs_input"
    assert result["runs"][0]["output"]["fact_claims"] == []
