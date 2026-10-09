"""Save actual workflow records; only a locally rechecked report can be final."""

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import UUID

from office_agents.agents.checker import check_draft
from office_agents.agents.writer import _plain_text
from office_agents.workflow_schemas import NodeRecord, WorkflowResult


class WorkflowExportError(RuntimeError):
    """Static messages intentionally exclude paths and business/provider content."""


def _atomic_text(path: Path, content: str) -> None:
    temporary = None
    try:
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=".pending-", delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def _approval_problems(result: WorkflowResult) -> bool:
    """Do not rely on status alone: callers may construct or mutate models."""
    requirements, outline = result.requirements, result.outline
    agent_data, draft, review = result.data_result, result.draft, result.review
    if (
        requirements is None
        or outline is None
        or agent_data is None
        or agent_data.status != "ready"
        or agent_data.data.status != "ok"
        or draft is None
        or review is None
        or not review.passed
        or review.needs_input
        or any(issue.severity == "error" for issue in review.issues)
        or result.error is not None
        or result.revision_count != 0
    ):
        return True
    try:
        for value in (requirements, outline, agent_data, draft, review, result.manager_decision):
            if (
                value is not None
                and type(value).model_validate(value.model_dump(mode="json")) != value
            ):
                return True
    except (ValueError, TypeError):
        return True
    if result.mode not in {"live", "offline_mock"}:
        return True
    data = agent_data.data
    if (
        data.run_id != result.run_id
        or result.manager_decision is None
        or result.manager_decision.status != "ready"
        or result.manager_decision.requirements != requirements
        or [node.role for node in result.nodes]
        != ["manager", "planner", "data", "writer", "checker"]
        or any(node.status != "passed" or node.error is not None for node in result.nodes)
        or any(event.run_id != result.run_id for event in result.events)
        or result.data_origin != requirements.data_origin
        or result.metrics != data.metrics
        or result.sources != data.sources
        or result.data_issues != data.data_issues
    ):
        return True
    outputs = (result.manager_decision, outline, agent_data, draft, review)
    if any(
        node.output != output.model_dump(mode="json")
        for node, output in zip(result.nodes, outputs, strict=True)
    ):
        return True
    return bool(check_draft(requirements, outline, data, draft))


def _report(result: WorkflowResult) -> str:
    requirements = result.requirements
    data = result.data_result.data
    origin = "模拟数据（仅用于实验演示）" if result.data_origin == "simulated" else "用户提供数据"
    mode = "离线模拟模型（offline_mock）" if result.mode == "offline_mock" else "真实模型（live）"
    metadata = [
        "# 工作报告",
        "",
        f"运行编号：{result.run_id}",
        "",
        f"运行模式：{mode}；数据来源类型：{origin}。",
        "",
        f"部门：{_plain_text(requirements.department)}；日期范围："
        f"{requirements.start_date.isoformat()}（含）至 "
        f"{requirements.end_date.isoformat()}（不含）。",
        "",
        "审核状态：四项结构化指标及其来源通过程序校验；Checker 模型审核通过。"
        "正文模型叙述待人工核实。",
        "",
    ]
    # check_draft already required exact deterministic rendering, including this heading.
    body = result.draft.markdown.removeprefix("# 工作报告草稿").lstrip()
    for section in result.draft.sections:
        heading_and_text = f"## {_plain_text(section.title)}\n\n{_plain_text(section.text)}"
        labelled = (
            f"## {_plain_text(section.title)}\n\n"
            f"模型叙述（待人工核实）：{_plain_text(section.text)}"
        )
        body = body.replace(heading_and_text, labelled, 1)
    lines = metadata + [body, "", "## 数据来源记录", ""]
    for source in data.sources:
        lines.extend(
            [
                f"- 来源：{_plain_text(source.source_id)}；文件："
                f"{_plain_text(source.file_name)}；原始记录数：{source.record_count}；"
                f"SHA256：{source.sha256}",
            ]
        )
    lines.extend(["", "统计采用的原始行：", ""])
    for metric in data.metrics:
        references = ", ".join(
            f"{_plain_text(ref.source_id)}:{ref.line_number}" for ref in metric.source_refs
        )
        lines.append(f"- {_plain_text(metric.metric_id)}：{references or '无匹配行'}")
    return "\n".join(lines).strip() + "\n"


def save_workflow(result: WorkflowResult, output_root: Path) -> Path:
    """Create a new run directory, retain failures, and never overwrite an old run."""
    try:
        if str(UUID(result.run_id)) != result.run_id:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise WorkflowExportError("Workflow run ID is invalid.") from None
    run_dir = Path(output_root) / result.run_id
    try:
        Path(output_root).mkdir(parents=True, exist_ok=True)
        run_dir.mkdir(exist_ok=False)
    except FileExistsError:
        raise WorkflowExportError(
            "Workflow run directory already exists; overwrite refused."
        ) from None
    except OSError:
        raise WorkflowExportError("Workflow output directory could not be created.") from None
    try:
        _atomic_text(run_dir / "run.json", _json(result.model_dump(mode="json")))
        events = "".join(
            json.dumps(event.model_dump(mode="json"), ensure_ascii=False, allow_nan=False) + "\n"
            for event in result.events
        )
        _atomic_text(run_dir / "events.jsonl", events)
        node_dir = run_dir / "nodes"
        node_dir.mkdir()
        for index, node in enumerate(result.nodes, start=1):
            # Assignment validation is disabled on contracts: recheck before using
            # role as a filename component, even for non-completed workflows.
            NodeRecord.model_validate(node.model_dump(mode="json"))
            _atomic_text(
                node_dir / f"{index:02d}-{node.role}.json", _json(node.model_dump(mode="json"))
            )
        if result.draft is not None:
            status = (
                "审核通过（导出门禁待复核）"
                if result.status == "completed"
                else "审核未通过"
                if result.status == "review_failed"
                else "待审核，尚未形成最终报告"
            )
            _atomic_text(
                run_dir / "draft.md", f"> 审核状态：{status}。\n\n{result.draft.markdown}\n"
            )
        if result.status == "completed":
            if _approval_problems(result):
                if result.draft is not None:
                    _atomic_text(
                        run_dir / "draft.md",
                        "> 审核状态：审核未通过（最终导出复核失败）。\n\n"
                        + result.draft.markdown
                        + "\n",
                    )
                raise WorkflowExportError("Final report export rejected by local validation.")
            _atomic_text(
                run_dir / "draft.md",
                "> 审核状态：审核通过（最终导出复核通过）。\n\n" + result.draft.markdown + "\n",
            )
            _atomic_text(run_dir / "report.md", _report(result))
    except WorkflowExportError:
        raise
    except (OSError, ValueError, TypeError, AttributeError):
        raise WorkflowExportError("Workflow artifacts could not be saved.") from None
    return run_dir
