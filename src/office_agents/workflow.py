"""Execute the actual five-role LangGraph, keeping immutable audit snapshots.

The deterministic tool creates a standalone DataResult UUID. At the Data node
boundary its validated copy is associated with this workflow's run_id; values,
source references and creation time remain the actual tool output.
"""

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from office_agents.agent_runtime import AgentSession
from office_agents.agent_schemas import (
    DataAgentResult,
    Draft,
    ManagerDecision,
    Outline,
    Requirements,
    Review,
    Role,
)
from office_agents.agents.checker import run_checker
from office_agents.agents.data import run_data_agent
from office_agents.agents.manager import run_manager
from office_agents.agents.planner import run_planner
from office_agents.agents.writer import render_draft, run_writer
from office_agents.llm import ModelCallError
from office_agents.schemas import DataIssue, Metric, SourceRecord
from office_agents.workflow_schemas import (
    NodeRecord,
    RevisionRecord,
    WorkflowEvent,
    WorkflowResult,
    WorkflowStatus,
)


class WorkflowState(TypedDict):
    run_id: str
    created_at: str
    mode: Literal["live", "offline_mock"]
    status: WorkflowStatus
    user_text: str
    data_origin: Literal["simulated", "provided"]
    manager_decision: ManagerDecision | None
    requirements: Requirements | None
    outline: Outline | None
    data_result: DataAgentResult | None
    metrics: list[Metric]
    sources: list[SourceRecord]
    data_issues: list[DataIssue]
    draft: Draft | None
    review: Review | None
    revision_count: int
    max_revisions: int
    revision_history: list[RevisionRecord]
    test_scenario: Literal["none", "bad-fact", "missing-section", "always-bad"]
    schema_version: Literal["0.5"]
    narrative_policy: Literal["constrained"]
    logical_request_count: int
    retry_count: int
    retry_budget: int
    nodes: list[NodeRecord]
    events: list[WorkflowEvent]
    request_count: int
    reserved_output_tokens: int
    usage: dict[str, int | None]
    error: str | None


def _utc_now():
    return datetime.now(UTC).isoformat()


def _validated(model, value):
    """Revalidate and copy role output before admitting it to shared state."""
    return model.model_validate(value.model_dump(mode="json"))


def _safe_node_error(role: Role, error: Exception) -> str:
    """Expose only exact known local diagnoses, never arbitrary exception text."""
    known = {
        "Agent request budget exhausted.": "request budget exhausted",
        "Agent output budget exhausted.": "output budget exhausted",
        "Agent output failed local JSON validation.": "role JSON validation failed",
        "Agent response was truncated or blocked.": "model response truncated or blocked",
        "Data Agent authorized tool execution failed.": "authorized data tool execution failed",
        "Manager returned invalid or ungrounded requirements.": (
            "Manager requirements invalid or ungrounded"
        ),
        "Planner returned an invalid section or metric plan.": (
            "Planner section or metric plan invalid"
        ),
    }
    reason = None
    if isinstance(error, ModelCallError) and len(error.args) == 1 and type(error.args[0]) is str:
        reason = known.get(error.args[0])
    if reason is not None:
        return f"{role.capitalize()} node failed: {reason}; inspect safe audit events and inputs."
    return f"{role.capitalize()} node failed; inspect safe audit events and inputs."


def run_workflow(
    user_text: str,
    data_root: str | Path,
    session: AgentSession,
    *,
    data_origin: Literal["simulated", "provided"] = "provided",
    run_id: str | None = None,
    max_revisions: int = 2,
    test_scenario: Literal["none", "bad-fact", "missing-section", "always-bad"] = "none",
) -> WorkflowResult:
    """Run one dedicated session with at most two genuine Writer revisions.

    This function never loads environment settings, changes budgets, retries, or
    exports files. The caller chooses live/mock mode and the authorized data path.
    """
    if (
        session.request_count
        or session.reserved_output_tokens
        or session.events
        or session.logical_request_count
        or session.retry_count
    ):
        raise ValueError("Workflow requires a fresh dedicated agent session.")
    initial = WorkflowResult(
        user_text=user_text,
        data_origin=data_origin,
        mode=session.mode,
        max_revisions=max_revisions,
        test_scenario=test_scenario,
        retry_budget=session.retry_budget,
        **({"run_id": run_id} if run_id is not None else {}),
    )
    # Python-mode values preserve typed contracts for node consumers.
    state = {field: deepcopy(getattr(initial, field)) for field in type(initial).model_fields}

    def execute(role: Role, inputs, action):
        def node(current):
            started_at, started = _utc_now(), monotonic()
            event_offset = len(session.events)
            snapshots = deepcopy(inputs(current))
            revision_index = current["revision_count"]
            output = None
            generated_output = None
            updates = {}
            node_status = "failed"
            error = None
            try:
                output, node_status, updates = action(current)
                generated_output = updates.pop("_generated_output", None)
                output = output.model_dump(mode="json")
            except Exception as failure:
                # Exceptions may contain keys, raw provider text or uploaded data.
                # Retain execution events and a fixed actionable role location only.
                error = _safe_node_error(role, failure)
                updates = {"status": "failed", "error": error}
            duration = max(0.0, (monotonic() - started) * 1000)
            finished_at = _utc_now()
            record = NodeRecord(
                role=role,
                started_at=started_at,
                finished_at=finished_at,
                duration_ms=duration,
                status=node_status,
                input=snapshots,
                output=output,
                error=error,
                revision_index=revision_index,
                generated_output=generated_output,
            )
            events = [
                WorkflowEvent(
                    run_id=current["run_id"],
                    created_at=started_at,
                    role=role,
                    event_type="node_started",
                    status="running",
                    summary=f"Started {role} with validated workflow inputs.",
                    revision_index=revision_index,
                )
            ]
            for event in session.events[event_offset:]:
                events.append(
                    WorkflowEvent(
                        run_id=current["run_id"],
                        revision_index=revision_index,
                        **event.model_dump(mode="json"),
                    )
                )
            if generated_output is not None:
                events.append(
                    WorkflowEvent(
                        run_id=current["run_id"],
                        created_at=finished_at,
                        role=role,
                        event_type="error_injected",
                        status="passed",
                        revision_index=revision_index,
                        summary="Explicit test scenario injected after validated Writer output.",
                        arguments={"test_scenario": current["test_scenario"]},
                    )
                )
            events.append(
                WorkflowEvent(
                    run_id=current["run_id"],
                    created_at=finished_at,
                    role=role,
                    event_type="node_finished",
                    status=node_status,
                    duration_ms=duration,
                    summary=error or f"Finished {role}; workflow decision: {node_status}.",
                    revision_index=revision_index,
                )
            )
            return {
                **updates,
                "nodes": [*current["nodes"], record],
                "events": [*current["events"], *events],
                "request_count": session.request_count,
                "logical_request_count": session.logical_request_count,
                "retry_count": session.retry_count,
                "reserved_output_tokens": session.reserved_output_tokens,
                "usage": deepcopy(session.usage_statistics),
            }

        return node

    def manager(current):
        output = _validated(
            ManagerDecision,
            run_manager(current["user_text"], session, data_origin=current["data_origin"]),
        )
        status = "passed" if output.status == "ready" else "needs_input"
        return (
            output,
            status,
            {
                "manager_decision": output,
                "requirements": deepcopy(output.requirements),
                "status": "running" if status == "passed" else "needs_input",
            },
        )

    def planner(current):
        output = _validated(Outline, run_planner(deepcopy(current["requirements"]), session))
        return output, "passed", {"outline": output}

    def data(current):
        output = _validated(
            DataAgentResult,
            run_data_agent(deepcopy(current["requirements"]), data_root, session),
        )
        linked_data = output.data.model_dump(mode="json")
        linked_data["run_id"] = current["run_id"]
        output = DataAgentResult.model_validate(
            {**output.model_dump(mode="json"), "data": linked_data}
        )
        ready = output.status == "ready" and output.data.status == "ok"
        status = "passed" if ready else "needs_input"
        return (
            output,
            status,
            {
                "data_result": output,
                "metrics": deepcopy(output.data.metrics),
                "sources": deepcopy(output.data.sources),
                "data_issues": deepcopy(output.data.data_issues),
                "status": "running" if ready else "needs_input",
            },
        )

    def writer(current):
        output = _validated(
            Draft,
            run_writer(
                deepcopy(current["requirements"]),
                deepcopy(current["outline"]),
                deepcopy(current["data_result"].data),
                session,
                previous_draft=deepcopy(current["draft"]),
                review=deepcopy(current["review"]),
                strict_narrative=True,
            ),
        )
        updates = {"draft": output}
        scenario = current["test_scenario"]
        if scenario != "none" and (current["revision_count"] == 0 or scenario == "always-bad"):
            updates["_generated_output"] = output.model_dump(mode="json")
            output = deepcopy(output)
            if scenario in {"bad-fact", "always-bad"}:
                metric = next(
                    metric
                    for metric in current["data_result"].data.metrics
                    if metric.metric_id == "project_count"
                )
                claim = next(
                    fact for fact in output.fact_claims if fact.metric_id == "project_count"
                )
                claim.value = metric.value + 1
            elif len(output.sections) > 1:
                output.sections.pop()
            else:
                output.sections[0].title = "实验注入的缺失章节"
            output.markdown = render_draft(output)
            output = _validated(Draft, output)
            updates["draft"] = output
        return output, "passed", updates

    def checker(current):
        request_offset = session.request_count
        output = _validated(
            Review,
            run_checker(
                deepcopy(current["requirements"]),
                deepcopy(current["outline"]),
                deepcopy(current["data_result"].data),
                deepcopy(current["draft"]),
                session,
                strict_narrative=True,
                skip_model_on_local_errors=True,
            ),
        )
        status = (
            "passed" if output.passed else "needs_input" if output.needs_input else "review_failed"
        )
        history = RevisionRecord(
            revision_index=current["revision_count"],
            draft=deepcopy(current["draft"]),
            review=deepcopy(output),
            writer_node_index=len(current["nodes"]) - 1,
            checker_node_index=len(current["nodes"]),
            review_mode=(
                "program_and_model" if session.request_count > request_offset else "program_only"
            ),
        )
        can_revise = (
            status == "review_failed" and current["revision_count"] < current["max_revisions"]
        )
        return (
            output,
            status,
            {
                "review": output,
                "revision_history": [*current["revision_history"], history],
                "status": "completed"
                if status == "passed"
                else "running"
                if can_revise
                else status,
                "revision_count": current["revision_count"] + int(can_revise),
            },
        )

    def requirements_input(current):
        return {"requirements": current["requirements"].model_dump(mode="json")}

    def report_input(current):
        return {
            **requirements_input(current),
            "outline": current["outline"].model_dump(mode="json"),
            "data": current["data_result"].data.model_dump(mode="json"),
        }

    graph = StateGraph(WorkflowState)
    graph.add_node(
        "manager",
        execute(
            "manager",
            lambda current: {
                "user_text": current["user_text"],
                "data_origin": current["data_origin"],
            },
            manager,
        ),
    )
    graph.add_node("planner", execute("planner", requirements_input, planner))
    graph.add_node(
        "data",
        execute(
            "data",
            lambda current: {**requirements_input(current), "data_root": str(data_root)},
            data,
        ),
    )
    graph.add_node(
        "writer",
        execute(
            "writer",
            lambda current: {
                **report_input(current),
                "previous_draft": current["draft"].model_dump(mode="json")
                if current["draft"]
                else None,
                "review": current["review"].model_dump(mode="json") if current["review"] else None,
                "strict_narrative": True,
            },
            writer,
        ),
    )
    graph.add_node(
        "checker",
        execute(
            "checker",
            lambda current: {
                **report_input(current),
                "draft": current["draft"].model_dump(mode="json"),
                "strict_narrative": True,
                "skip_model_on_local_errors": True,
            },
            checker,
        ),
    )
    graph.add_edge(START, "manager")
    for current, following in (
        ("manager", "planner"),
        ("planner", "data"),
        ("data", "writer"),
        ("writer", "checker"),
    ):
        graph.add_conditional_edges(
            current,
            lambda current_state, next_node=following: (
                next_node if current_state["status"] == "running" else END
            ),
            {following: following, END: END},
        )
    graph.add_conditional_edges(
        "checker",
        lambda current: "writer" if current["status"] == "running" else END,
        {"writer": "writer", END: END},
    )
    final_state = graph.compile().invoke(state)
    return WorkflowResult.model_validate(final_state)
