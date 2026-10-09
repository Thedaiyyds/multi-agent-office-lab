"""Independent export gate and audit persistence tests, without model requests."""

import json
from pathlib import Path

import pytest

from office_agents.agent_runtime import AgentSession
from office_agents.agents.writer import render_draft
from office_agents.config import Settings
from office_agents.workflow import run_workflow
from office_agents.workflow_examples import make_workflow_mock_transport
from office_agents.workflow_export import WorkflowExportError, save_workflow
from office_agents.workflow_schemas import WorkflowResult


@pytest.fixture
def completed_result():
    with_session = AgentSession(
        Settings(base_url="https://mock.invalid", model="export-fixture"),
        mode="offline_mock",
        max_requests=6,
        max_total_output_tokens=1984,
        transport=make_workflow_mock_transport(),
    )
    try:
        result = run_workflow(
            "生成研发部2026年第二季度工作报告",
            "data/samples",
            with_session,
            data_origin="simulated",
            max_revisions=0,
        )
        assert result.status == "completed"
        return result
    finally:
        with_session.close()


def _sync_audit(result):
    """Explicit synthetic mutation fixtures, never production evidence."""
    result.manager_decision.requirements = result.requirements.model_copy(deep=True)
    req = result.requirements.model_dump(mode="json")
    data = result.data_result.data.model_dump(mode="json")
    base = {"requirements": req, "outline": result.outline.model_dump(mode="json"), "data": data}
    result.nodes[0].input = {"user_text": result.user_text, "data_origin": result.data_origin}
    result.nodes[0].output = result.manager_decision.model_dump(mode="json")
    result.nodes[1].input = {"requirements": req}
    result.nodes[1].output = result.outline.model_dump(mode="json")
    result.nodes[2].input["requirements"] = req
    result.nodes[2].output = result.data_result.model_dump(mode="json")
    result.nodes[3].input = {
        **base,
        "previous_draft": None,
        "review": None,
        "strict_narrative": True,
    }
    result.nodes[3].output = result.draft.model_dump(mode="json")
    result.nodes[4].input = {
        **base,
        "draft": result.draft.model_dump(mode="json"),
        "strict_narrative": True,
        "skip_model_on_local_errors": True,
    }
    result.nodes[4].output = result.review.model_dump(mode="json")
    result.revision_history[0].draft = result.draft.model_copy(deep=True)
    result.revision_history[0].review = result.review.model_copy(deep=True)


def test_success_artifacts_preserve_actual_records_and_provenance(tmp_path, completed_result):
    result = completed_result
    directory = save_workflow(result, tmp_path)
    assert directory == tmp_path / result.run_id
    assert json.loads((directory / "run.json").read_text()) == result.model_dump(mode="json")
    events = [json.loads(line) for line in (directory / "events.jsonl").read_text().splitlines()]
    assert events == [event.model_dump(mode="json") for event in result.events]
    for index, node in enumerate(result.nodes, 1):
        path = directory / "nodes" / f"{index:02d}-{node.role}.json"
        assert json.loads(path.read_text()) == node.model_dump(mode="json")
    draft = (directory / "draft.md").read_text()
    assert draft.endswith(result.draft.markdown + "\n")
    assert "最终导出复核通过" in draft
    report = (directory / "report.md").read_text()
    assert report.startswith("# 工作报告\n")
    assert "# 工作报告草稿" not in report
    assert "模拟数据（仅用于实验演示）" in report
    assert "离线模拟模型" in report
    assert result.run_id in report
    assert "研发部" in report and "2026-04-01（含）至 2026-07-01（不含）" in report
    for source in result.sources:
        assert source.sha256 in report
    assert "projects.csv:3" in report
    assert "完成项目数 = 2" in report
    assert "未筛选，不可归因" in report
    assert "四项结构化指标及其来源通过程序校验；Checker 模型审核通过" in report
    assert "模型叙述仍以所列来源为依据" not in report
    assert "正文使用受约束范围说明" in report
    assert "模型叙述（待人工核实）：" not in report
    assert (directory / "revisions/00/draft.md").exists()
    assert json.loads(
        (directory / "revisions/00/review.json").read_text()
    ) == result.review.model_dump(mode="json")
    for line in result.draft.markdown.splitlines():
        if line.startswith(("- 事实：", "- 建议（尚未实施）：")):
            assert line in report


@pytest.mark.parametrize(
    "text",
    [
        "待" * 500,
        "整体工作按计划推进",
        "存在项目延期风险，部分项目资源分配紧张",
        "本季度完成项目九十九个",
    ],
)
def test_unsupported_model_prose_cannot_pass_final_export_even_if_model_approved(
    tmp_path, completed_result, text
):
    result = completed_result
    result.draft.sections[0].text = text
    result.draft.markdown = render_draft(result.draft)
    _sync_audit(result)
    original = result.model_dump(mode="json")
    with pytest.raises(WorkflowExportError, match="local validation"):
        save_workflow(result, tmp_path)
    directory = tmp_path / result.run_id
    assert not (directory / "report.md").exists()
    assert result.draft.markdown in (directory / "draft.md").read_text()
    assert json.loads((directory / "run.json").read_text()) == original
    assert result.model_dump(mode="json") == original


def test_escaped_heading_collision_keeps_each_constrained_section(tmp_path, completed_result):
    result = completed_result
    titles = ["概\n况", "概 况"]
    for index, title in enumerate(titles):
        result.requirements.required_sections[index] = title
        result.outline.sections[index].title = title
        result.draft.sections[index].title = title
    result.draft.markdown = render_draft(result.draft)
    _sync_audit(result)
    report = (save_workflow(result, tmp_path) / "report.md").read_text()
    sections = report.split("## 概 况\n\n")
    assert sections[1].startswith(result.draft.sections[0].text)
    assert sections[2].startswith(result.draft.sections[1].text)


def test_provided_live_metadata_is_explicit(tmp_path, completed_result):
    result = completed_result
    result.mode = "live"
    result.data_origin = "provided"
    result.requirements.data_origin = "provided"
    result.data_result.data.request.data_origin = "provided"
    _sync_audit(result)
    report = (save_workflow(result, tmp_path) / "report.md").read_text()
    assert "真实模型（live）" in report
    assert "数据来源类型：用户提供数据" in report


@pytest.mark.parametrize("status", ["review_failed", "failed", "needs_input", "running"])
def test_non_completed_preserves_draft_without_final(tmp_path, completed_result, status):
    result = completed_result
    result.status = status
    directory = save_workflow(result, tmp_path)
    assert (directory / "run.json").exists()
    assert not (directory / "report.md").exists()
    draft = (directory / "draft.md").read_text()
    assert result.draft.markdown in draft
    assert ("审核未通过" if status == "review_failed" else "待审核") in draft


def test_failure_before_writer_still_saves_audit(tmp_path):
    result = WorkflowResult(
        mode="offline_mock", status="failed", user_text="做报告", data_origin="provided"
    )
    directory = save_workflow(result, tmp_path)
    assert json.loads((directory / "run.json").read_text())["status"] == "failed"
    assert (directory / "events.jsonl").read_text() == ""
    assert list((directory / "nodes").iterdir()) == []
    assert not (directory / "draft.md").exists()
    assert not (directory / "report.md").exists()


@pytest.mark.parametrize(
    "tamper",
    [
        "metrics",
        "sources",
        "issues",
        "origin",
        "review",
        "markdown",
        "facts",
        "nodes",
        "run_id",
        "event",
    ],
)
def test_tampering_cannot_export_final(tmp_path, completed_result, tamper):
    result = completed_result.model_copy(deep=True)
    if tamper == "metrics":
        result.metrics = []
    elif tamper == "sources":
        result.sources = []
    elif tamper == "issues":
        result.data_issues = []
        # Normal data may have no warnings, so force an inconsistent nested issue list.
        from office_agents.schemas import DataIssue

        result.data_result.data.data_issues = [
            DataIssue(severity="warning", code="new_warning", message="记录不一致")
        ]
    elif tamper == "origin":
        result.data_origin = "provided"
    elif tamper == "review":
        result.review.passed = False
    elif tamper == "markdown":
        result.draft.markdown += "\n## 伪造通过审核的正文"
        result.nodes[3].output = result.draft.model_dump(mode="json")
    elif tamper == "facts":
        result.draft.fact_claims[0].value = 99
        result.draft.markdown = render_draft(result.draft)
        result.nodes[3].output = result.draft.model_dump(mode="json")
    elif tamper == "nodes":
        result.nodes.pop()
    elif tamper == "run_id":
        result.data_result.data.run_id = "a different data run"
    elif tamper == "event":
        result.events[0].run_id = "a different workflow"
    with pytest.raises(WorkflowExportError, match="local validation"):
        save_workflow(result, tmp_path)
    directory = tmp_path / result.run_id
    assert (directory / "run.json").exists()
    assert "审核未通过" in (directory / "draft.md").read_text()
    assert not (directory / "report.md").exists()


@pytest.mark.parametrize("node_index", range(5))
def test_each_node_snapshot_must_match_final_state(tmp_path, completed_result, node_index):
    completed_result.nodes[node_index].output = {"altered": True}
    with pytest.raises(WorkflowExportError, match="local validation"):
        save_workflow(completed_result, tmp_path)
    assert not (tmp_path / completed_result.run_id / "report.md").exists()


def test_repeated_run_id_refuses_overwrite_and_other_run_is_isolated(tmp_path, completed_result):
    first = save_workflow(completed_result, tmp_path)
    original = (first / "run.json").read_bytes()
    with pytest.raises(WorkflowExportError, match="overwrite refused"):
        save_workflow(completed_result, tmp_path)
    assert (first / "run.json").read_bytes() == original
    second = WorkflowResult(
        mode="offline_mock", status="needs_input", user_text="做报告", data_origin="provided"
    )
    assert save_workflow(second, tmp_path) != first
    assert (first / "report.md").exists()


def test_collision_with_symlink_refuses_writes(tmp_path, completed_result):
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / completed_result.run_id).symlink_to(outside, target_is_directory=True)
    with pytest.raises(WorkflowExportError, match="overwrite refused"):
        save_workflow(completed_result, tmp_path)
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize(
    "invalid", ["../escape", "not-a-uuid", "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"]
)
def test_invalid_mutated_uuid_rejected_before_directory_creation(
    tmp_path, completed_result, invalid
):
    completed_result.run_id = invalid
    with pytest.raises(WorkflowExportError, match="run ID is invalid"):
        save_workflow(completed_result, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_report_write_failure_does_not_leave_partial_final(tmp_path, completed_result, monkeypatch):
    replace = Path.replace

    def fail_final(self, target):
        if target.name == "report.md":
            raise OSError("sensitive filesystem detail")
        return replace(self, target)

    monkeypatch.setattr(Path, "replace", fail_final)
    with pytest.raises(WorkflowExportError) as error:
        save_workflow(completed_result, tmp_path)
    assert str(error.value) == "Workflow artifacts could not be saved."
    directory = tmp_path / completed_result.run_id
    assert not (directory / "report.md").exists()
    assert not list(directory.glob(".pending-*"))
    assert (directory / "draft.md").exists()
    assert (directory / "run.json").exists()


def test_metadata_escapes_untrusted_department_structure(tmp_path, completed_result):
    result = completed_result
    department = "研发部\n# injected [link](https://example.test)"
    result.requirements.department = department
    result.data_result.data.request.department = department
    _sync_audit(result)
    report = (save_workflow(result, tmp_path) / "report.md").read_text()
    assert "\n# injected" not in report
    assert "\\# injected \\[link\\]" in report


@pytest.mark.parametrize("status", ["completed", "failed"])
def test_mutated_node_role_cannot_escape_audit_directory(tmp_path, completed_result, status):
    completed_result.status = status
    completed_result.nodes[0].role = "../../outside"
    with pytest.raises(WorkflowExportError, match="artifacts could not be saved"):
        save_workflow(completed_result, tmp_path)
    directory = tmp_path / completed_result.run_id
    assert (directory / "run.json").exists()
    assert list((directory / "nodes").iterdir()) == []
    assert not (directory / "report.md").exists()


def test_source_metadata_model_mutation_does_not_bypass_report_gate(tmp_path, completed_result):
    result = completed_result
    result.data_result.data.sources[0].sha256 = "\n# forged source metadata"
    result.sources[0].sha256 = result.data_result.data.sources[0].sha256
    result.nodes[2].output = result.data_result.model_dump(mode="json")
    with pytest.raises(WorkflowExportError, match="local validation"):
        save_workflow(result, tmp_path)
    assert not (tmp_path / result.run_id / "report.md").exists()
