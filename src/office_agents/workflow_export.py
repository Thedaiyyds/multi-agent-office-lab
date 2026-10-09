"""Save actual workflow records; only a locally rechecked report can be final."""

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import UUID

from office_agents.agent_schemas import Draft
from office_agents.agents.checker import check_draft
from office_agents.agents.writer import _plain_text, render_draft
from office_agents.workflow_schemas import NodeRecord, RevisionRecord, WorkflowResult


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
    """Recheck every historical boundary before promoting the final report."""
    try:
        WorkflowResult.model_validate(result.model_dump(mode="json"))
        requirements, outline = result.requirements, result.outline
        agent_data, draft, review = result.data_result, result.draft, result.review
        if (
            result.status != "completed"
            or result.error is not None
            or requirements is None
            or outline is None
            or agent_data is None
            or agent_data.status != "ready"
            or agent_data.data.status != "ok"
            or draft is None
            or review is None
            or not review.passed
            or review.needs_input
            or any(issue.severity == "error" for issue in review.issues)
            or result.manager_decision is None
            or result.manager_decision.status != "ready"
            or result.manager_decision.requirements != requirements
            or result.data_origin != requirements.data_origin
            or agent_data.data.run_id != result.run_id
            or result.metrics != agent_data.data.metrics
            or result.sources != agent_data.data.sources
            or result.data_issues != agent_data.data.data_issues
            or any(event.run_id != result.run_id for event in result.events)
        ):
            return True
        requests = [event for event in result.events if event.event_type == "model_request"]
        retries = [event for event in result.events if event.event_type == "model_retry"]
        if (
            result.request_count != len(requests)
            or any(event.max_output_tokens is None for event in requests)
            or result.reserved_output_tokens != sum(event.max_output_tokens for event in requests)
            or result.logical_request_count != sum(event.attempt == 1 for event in requests)
            or result.retry_count != len(retries)
            or result.retry_count != sum(event.attempt == 2 for event in requests)
        ):
            return True
        for position, event in enumerate(requests):
            if event.status not in {"passed", "failed"}:
                return True
            if event.attempt == 2:
                if position == 0:
                    return True
                previous_event = requests[position - 1]
                if (
                    previous_event.attempt != 1
                    or previous_event.status != "failed"
                    or previous_event.role != event.role
                    or previous_event.revision_index != event.revision_index
                    or previous_event.max_output_tokens != event.max_output_tokens
                ):
                    return True
            if event.status == "failed" and (
                position + 1 == len(requests) or requests[position + 1].attempt != 2
            ):
                return True
        retry_requests = [event for event in requests if event.attempt == 2]
        for event, retry in zip(retries, retry_requests, strict=True):
            if (
                event.role != retry.role
                or event.revision_index != retry.revision_index
                or event.attempt != 2
                or event.status != "passed"
                or event.max_output_tokens != retry.max_output_tokens
            ):
                return True
        starts = [event for event in result.events if event.event_type == "node_started"]
        finishes = [event for event in result.events if event.event_type == "node_finished"]
        if len(starts) != len(result.nodes) or len(finishes) != len(result.nodes):
            return True
        for node, start, finish in zip(result.nodes, starts, finishes, strict=True):
            if (
                start.role != node.role
                or finish.role != node.role
                or start.revision_index != node.revision_index
                or finish.revision_index != node.revision_index
                or start.status != "running"
                or finish.status != node.status
                or start.created_at != node.started_at
                or finish.created_at != node.finished_at
                or finish.duration_ms != node.duration_ms
            ):
                return True
        history = result.revision_history
        expected_roles = ["manager", "planner", "data"] + ["writer", "checker"] * len(history)
        if [node.role for node in result.nodes] != expected_roles:
            return True
        req_json = requirements.model_dump(mode="json")
        data_json = agent_data.data.model_dump(mode="json")
        base = {
            "requirements": req_json,
            "outline": outline.model_dump(mode="json"),
            "data": data_json,
        }
        base_outputs = (result.manager_decision, outline, agent_data)
        for node, output in zip(result.nodes[:3], base_outputs, strict=True):
            if (
                node.status != "passed"
                or node.error is not None
                or node.revision_index != 0
                or node.generated_output is not None
                or node.output != output.model_dump(mode="json")
            ):
                return True
        if result.nodes[0].input != {
            "user_text": result.user_text,
            "data_origin": result.data_origin,
        }:
            return True
        if result.nodes[1].input != {"requirements": req_json}:
            return True
        if result.nodes[2].input.get("requirements") != req_json:
            return True
        for index, revision in enumerate(history):
            writer_index, checker_index = 3 + index * 2, 4 + index * 2
            if (
                revision.revision_index != index
                or revision.writer_node_index != writer_index
                or revision.checker_node_index != checker_index
            ):
                return True
            writer, checker = result.nodes[writer_index], result.nodes[checker_index]
            previous = history[index - 1] if index else None
            expected_writer_input = {
                **base,
                "previous_draft": previous.draft.model_dump(mode="json") if previous else None,
                "review": previous.review.model_dump(mode="json") if previous else None,
                "strict_narrative": True,
            }
            expected_checker_input = {
                **base,
                "draft": revision.draft.model_dump(mode="json"),
                "strict_narrative": True,
                "skip_model_on_local_errors": True,
            }
            expected_status = "passed" if revision.review.passed else "review_failed"
            if (
                writer.input != expected_writer_input
                or checker.input != expected_checker_input
                or writer.status != "passed"
                or checker.status != expected_status
                or writer.error is not None
                or checker.error is not None
                or writer.revision_index != index
                or checker.revision_index != index
                or writer.output != revision.draft.model_dump(mode="json")
                or checker.output != revision.review.model_dump(mode="json")
                or checker.generated_output is not None
            ):
                return True
            injected = result.test_scenario != "none" and (
                index == 0 or result.test_scenario == "always-bad"
            )
            injection_events = [
                event
                for event in result.events
                if event.event_type == "error_injected" and event.revision_index == index
            ]
            if (
                injected != (writer.generated_output is not None)
                or len(injection_events) != int(injected)
                or any(
                    event.role != "writer"
                    or event.arguments != {"test_scenario": result.test_scenario}
                    for event in injection_events
                )
            ):
                return True
            if injected:
                generated = Draft.model_validate(writer.generated_output)
                if generated.markdown != render_draft(generated):
                    return True
                altered = generated.model_copy(deep=True)
                if result.test_scenario in {"bad-fact", "always-bad"}:
                    metric = next(
                        metric
                        for metric in agent_data.data.metrics
                        if metric.metric_id == "project_count"
                    )
                    fact = next(
                        fact for fact in altered.fact_claims if fact.metric_id == "project_count"
                    )
                    fact.value = metric.value + 1
                elif len(altered.sections) > 1:
                    altered.sections.pop()
                else:
                    altered.sections[0].title = "实验注入的缺失章节"
                altered.markdown = render_draft(altered)
                if altered != revision.draft:
                    return True
            model_events = [
                event
                for event in result.events
                if event.role == "checker"
                and event.revision_index == index
                and event.event_type == "model_request"
            ]
            mode = "program_and_model" if model_events else "program_only"
            if revision.review_mode != mode or (
                revision.review.passed and (not model_events or model_events[-1].status != "passed")
            ):
                return True
            for node in (writer, checker):
                finishes = [
                    event
                    for event in result.events
                    if event.role == node.role
                    and event.revision_index == index
                    and event.event_type == "node_finished"
                ]
                if (
                    len(finishes) != 1
                    or finishes[0].status != node.status
                    or finishes[0].duration_ms != node.duration_ms
                ):
                    return True
            local = check_draft(
                requirements, outline, agent_data.data, revision.draft, strict_narrative=True
            )
            if revision.review.passed and local:
                return True
            if revision.review_mode == "program_only" and not local:
                return True
        return bool(
            check_draft(requirements, outline, agent_data.data, draft, strict_narrative=True)
        )
    except (ValueError, TypeError, AttributeError, IndexError, StopIteration, OverflowError):
        return True


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
        "正文使用受约束范围说明；建议尚未实施，需人工评估。",
        "",
    ]
    # check_draft already required exact deterministic rendering, including this heading.
    body = result.draft.markdown.removeprefix("# 工作报告草稿").lstrip()
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
        revision_dir = run_dir / "revisions"
        revision_dir.mkdir()
        for revision in result.revision_history:
            RevisionRecord.model_validate(revision.model_dump(mode="json"))
            directory = revision_dir / f"{revision.revision_index:02d}"
            directory.mkdir(exist_ok=False)
            label = "审核通过" if revision.review.passed else "审核未通过"
            _atomic_text(
                directory / "draft.md", f"> 审核状态：{label}。\n\n{revision.draft.markdown}\n"
            )
            _atomic_text(directory / "review.json", _json(revision.review.model_dump(mode="json")))
        reviewed_indices = {revision.revision_index for revision in result.revision_history}
        for node in result.nodes:
            if (
                node.role == "writer"
                and node.status == "passed"
                and node.output is not None
                and node.revision_index not in reviewed_indices
            ):
                # A successful Writer can be followed by a failed Checker. Preserve
                # that actual version without inventing an unavailable review.
                pending_draft = Draft.model_validate(node.output)
                directory = revision_dir / f"{node.revision_index:02d}"
                directory.mkdir(exist_ok=False)
                _atomic_text(
                    directory / "draft.md",
                    "> 审核状态：待审核，Checker 未完成，尚未形成最终报告。\n\n"
                    + pending_draft.markdown
                    + "\n",
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
