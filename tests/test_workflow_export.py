"""Independent export gate and audit persistence tests, without model requests."""

import json
from pathlib import Path

import pytest

from office_agents.agent_examples import sample_content, sample_outline, sample_requirements
from office_agents.agent_schemas import DataAgentResult, Draft, ManagerDecision, Review
from office_agents.agents.writer import render_draft
from office_agents.schemas import DataRequest
from office_agents.tools.metrics import run_data_tools
from office_agents.workflow_export import WorkflowExportError, save_workflow
from office_agents.workflow_schemas import NodeRecord, WorkflowEvent, WorkflowResult

SAMPLES = Path(__file__).resolve().parents[1] / "data" / "samples"


@pytest.fixture
def completed_result():
    requirements = sample_requirements()
    outline = sample_outline(requirements)
    data = run_data_tools(
        SAMPLES,
        DataRequest.model_validate(
            requirements.model_dump(exclude={"required_sections", "output_format"})
        ),
    )
    content = sample_content(outline, data)
    draft = Draft(**content.model_dump(), markdown=render_draft(content))
    manager = ManagerDecision(status="ready", requirements=requirements)
    data_agent = DataAgentResult(status="ready", data=data, summary="离线测试数据。")
    review = Review(passed=True)
    result = WorkflowResult(
        mode="offline_mock",
        status="completed",
        user_text="生成研发部2026年第二季度工作报告",
        data_origin="simulated",
        manager_decision=manager,
        requirements=requirements,
        outline=outline,
        data_result=data_agent,
        metrics=data.metrics,
        sources=data.sources,
        data_issues=data.data_issues,
        draft=draft,
        review=review,
    )
    result.data_result.data.run_id = result.run_id
    for role, output in zip(
        ["manager", "planner", "data", "writer", "checker"],
        [manager, outline, data_agent, draft, review],
        strict=True,
    ):
        result.nodes.append(
            NodeRecord(
                role=role,
                started_at=result.created_at,
                finished_at=result.created_at,
                duration_ms=1,
                status="passed",
                input={"fixture": "explicit independent export test"},
                output=output.model_dump(mode="json"),
            )
        )
        result.events.append(
            WorkflowEvent(
                run_id=result.run_id,
                created_at=result.created_at,
                role=role,
                event_type="node_finished",
                status="passed",
                duration_ms=1,
                summary="独立导出测试记录，非运行证据。",
            )
        )
    return result


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
    assert report.count("模型叙述（待人工核实）：") == len(result.draft.sections)
    for line in result.draft.markdown.splitlines():
        if line.startswith(("- 事实：", "- 建议（尚未实施）：")):
            assert line in report


def test_long_section_text_labels_only_report_without_changing_actual_evidence(
    tmp_path, completed_result
):
    result = completed_result
    result.draft.sections[0].text = "待" * 500
    result.draft.markdown = render_draft(result.draft)
    result.nodes[3].output = result.draft.model_dump(mode="json")
    before = result.model_dump(mode="json")
    directory = save_workflow(result, tmp_path)
    report = (directory / "report.md").read_text()
    assert "模型叙述（待人工核实）：" + "待" * 500 in report
    assert (directory / "draft.md").read_text().endswith(result.draft.markdown + "\n")
    assert "模型叙述（待人工核实）：" not in result.draft.markdown
    assert json.loads((directory / "run.json").read_text()) == before
    assert json.loads((directory / "nodes" / "04-writer.json").read_text()) == before["nodes"][3]
    assert result.model_dump(mode="json") == before


def test_unsupported_model_prose_remains_visible_with_human_verification_label(
    tmp_path, completed_result
):
    result = completed_result
    texts = ["整体工作按计划推进", "存在项目延期风险，部分项目资源分配紧张"]
    for section, text in zip(result.draft.sections, texts):
        section.text = text
    result.draft.markdown = render_draft(result.draft)
    result.nodes[3].output = result.draft.model_dump(mode="json")
    original = result.model_dump(mode="json")
    directory = save_workflow(result, tmp_path)
    report = (directory / "report.md").read_text()
    for text in texts:
        assert f"模型叙述（待人工核实）：{text}" in report
    for line in result.draft.markdown.splitlines():
        if line.startswith("- 事实："):
            assert line in report
    assert json.loads((directory / "run.json").read_text()) == original
    assert (directory / "draft.md").read_text().endswith(result.draft.markdown + "\n")


def test_provided_live_metadata_is_explicit(tmp_path, completed_result):
    result = completed_result
    result.mode = "live"
    result.data_origin = "provided"
    result.requirements.data_origin = "provided"
    result.data_result.data.request.data_origin = "provided"
    result.nodes[0].output = result.manager_decision.model_dump(mode="json")
    result.nodes[2].output = result.data_result.model_dump(mode="json")
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
    result.nodes[0].output = result.manager_decision.model_dump(mode="json")
    result.nodes[2].output = result.data_result.model_dump(mode="json")
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
