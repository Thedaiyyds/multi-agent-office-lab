"""Public workflow CLI acceptance without credentials or provider requests."""

import json

import pytest

from office_agents.cli import main


@pytest.fixture(autouse=True)
def forbid_live_settings(monkeypatch):
    def forbidden():
        raise AssertionError("Offline workflow must not load model credentials.")

    monkeypatch.setattr("office_agents.cli.Settings.from_env", forbidden)


def run_command(tmp_path, request="生成研发部2026年第二季度工作报告", *extra):
    return ["run", "--request", request, "--output-dir", str(tmp_path), *extra]


def load_result(tmp_path):
    files = list(tmp_path.glob("*/run.json"))
    assert len(files) == 1
    return files[0].parent, json.loads(files[0].read_text())


def test_workflow_default_is_offline_and_exports_actual_chain(tmp_path, capsys):
    assert main(run_command(tmp_path)) == 0
    directory, result = load_result(tmp_path)
    assert result["mode"] == "offline_mock" and result["status"] == "completed"
    assert result["request_count"] == 6
    assert result["reserved_output_tokens"] == 1984
    assert result["usage"]["total_tokens"] is None
    assert result["data_origin"] == "simulated"
    assert [node["role"] for node in result["nodes"]] == [
        "manager",
        "planner",
        "data",
        "writer",
        "checker",
    ]
    assert (directory / "report.md").is_file()
    assert (directory / "draft.md").is_file()
    assert len(list((directory / "nodes").glob("*.json"))) == 5
    assert "no real model requests" in capsys.readouterr().out


@pytest.mark.parametrize(
    "user_text,counts",
    [
        ("生成市场部2026年第二季度工作报告", [1, 0, 0, 1]),
        ("生成研发部2026年第一季度工作报告", [2, 1, 0.5, 1]),
        ("部门：研发部 2026-04-01 到 2026-07-01 章节：成果,概况", [3, 2, 2 / 3, 2]),
    ],
)
def test_changed_requirements_reach_tools_and_report(tmp_path, user_text, counts):
    assert main(run_command(tmp_path, user_text)) == 0
    _, result = load_result(tmp_path)
    assert [metric["value"] for metric in result["metrics"]] == counts
    assert [section["title"] for section in result["draft"]["sections"]] == result["requirements"][
        "required_sections"
    ]
    assert result["draft"]["sections"][0]["section_id"] == "part_1"


@pytest.mark.parametrize(
    "user_text,node_count,request_count",
    [
        ("写个工作报告", 1, 1),
        ("生成研发部工作报告", 1, 1),
        ("生成财务部2026年第二季度工作报告", 3, 4),
    ],
)
def test_needs_input_has_no_final_report(tmp_path, user_text, node_count, request_count):
    assert main(run_command(tmp_path, user_text)) == 1
    directory, result = load_result(tmp_path)
    assert result["status"] == "needs_input"
    assert len(result["nodes"]) == node_count
    assert result["request_count"] == request_count
    assert not (directory / "report.md").exists()


def test_missing_files_early_stop_preserves_data_issues(tmp_path):
    assert (
        main(
            run_command(
                tmp_path, "生成研发部2026年第二季度工作报告", "--data-dir", str(tmp_path / "absent")
            )
        )
        == 1
    )
    directory, result = load_result(tmp_path)
    assert result["status"] == "needs_input" and result["request_count"] == 3
    assert result["data_origin"] == "provided"
    assert result["data_issues"] and not result["metrics"]
    assert not (directory / "report.md").exists()


def test_output_budget_stop_does_not_claim_success(tmp_path):
    assert (
        main(run_command(tmp_path, "生成研发部2026年第二季度工作报告", "--max-requests", "1")) == 1
    )
    directory, result = load_result(tmp_path)
    assert result["status"] == "failed" and result["request_count"] == 1
    assert len(result["nodes"]) == 2
    assert not (directory / "report.md").exists()


def test_runs_are_isolated_and_origin_is_caller_owned(tmp_path):
    command = run_command(tmp_path, "生成研发部2026年第二季度工作报告", "--data-origin", "provided")
    assert main(command) == main(command) == 0
    results = [json.loads(path.read_text()) for path in tmp_path.glob("*/run.json")]
    assert len(results) == 2 and results[0]["run_id"] != results[1]["run_id"]
    assert all(result["data_origin"] == "provided" for result in results)


def test_export_error_is_safe_and_nonzero(tmp_path, monkeypatch, capsys):
    from office_agents.workflow_export import WorkflowExportError

    def fail(*args, **kwargs):
        raise WorkflowExportError("private export data")

    monkeypatch.setattr("office_agents.workflow_export.save_workflow", fail)
    assert main(run_command(tmp_path)) == 1
    output = capsys.readouterr().out
    assert "private export data" not in output and "could not be saved" in output


def test_invalid_blank_request_cannot_create_final_report(tmp_path):
    assert main(run_command(tmp_path, "   ")) == 1
    assert not list(tmp_path.glob("*/report.md"))
