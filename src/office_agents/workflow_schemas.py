"""Serializable contracts for an actual five-role workflow and its audit trail."""

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from office_agents.agent_schemas import (
    DataAgentResult,
    Draft,
    ManagerDecision,
    Outline,
    Requirements,
    Review,
    Role,
)
from office_agents.schemas import ContractModel, DataIssue, Metric, SourceRecord

WorkflowStatus = Literal["running", "completed", "needs_input", "review_failed", "failed"]


class WorkflowEvent(ContractModel):
    run_id: str
    created_at: str
    role: Role
    event_type: Literal[
        "node_started",
        "node_finished",
        "model_request",
        "tool_execution",
        "model_retry",
        "error_injected",
    ]
    status: Literal["running", "passed", "needs_input", "review_failed", "failed"]
    duration_ms: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    summary: str
    tool_name: str | None = None
    arguments: dict[str, Any] | None = None
    revision_index: int = Field(default=0, ge=0, le=2, strict=True)
    attempt: int = Field(default=1, ge=1, le=2, strict=True)
    max_output_tokens: int | None = Field(default=None, ge=1, le=768, strict=True)


class NodeRecord(ContractModel):
    role: Role
    started_at: str
    finished_at: str
    duration_ms: float = Field(ge=0, allow_inf_nan=False)
    status: Literal["passed", "needs_input", "review_failed", "failed"]
    input: dict[str, Any]
    output: dict[str, Any] | None = None
    error: str | None = None
    revision_index: int = Field(default=0, ge=0, le=2, strict=True)
    generated_output: dict[str, Any] | None = None


class RevisionRecord(ContractModel):
    revision_index: int = Field(ge=0, le=2, strict=True)
    draft: Draft
    review: Review
    writer_node_index: int = Field(ge=0, strict=True)
    checker_node_index: int = Field(ge=0, strict=True)
    review_mode: Literal["program_only", "program_and_model"]


class WorkflowResult(ContractModel):
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    mode: Literal["live", "offline_mock"]
    status: WorkflowStatus = "running"
    user_text: str = Field(min_length=1, max_length=4000)
    data_origin: Literal["simulated", "provided"]
    manager_decision: ManagerDecision | None = None
    requirements: Requirements | None = None
    outline: Outline | None = None
    data_result: DataAgentResult | None = None
    metrics: list[Metric] = Field(default_factory=list)
    sources: list[SourceRecord] = Field(default_factory=list)
    data_issues: list[DataIssue] = Field(default_factory=list)
    draft: Draft | None = None
    review: Review | None = None
    schema_version: Literal["0.5"] = "0.5"
    max_revisions: int = Field(default=2, ge=0, le=2, strict=True)
    revision_count: int = Field(default=0, ge=0, le=2, strict=True)
    revision_history: list[RevisionRecord] = Field(default_factory=list, max_length=3)
    test_scenario: Literal["none", "bad-fact", "missing-section", "always-bad"] = "none"
    narrative_policy: Literal["constrained"] = "constrained"
    nodes: list[NodeRecord] = Field(default_factory=list)
    events: list[WorkflowEvent] = Field(default_factory=list)
    request_count: int = Field(default=0, ge=0)
    reserved_output_tokens: int = Field(default=0, ge=0)
    logical_request_count: int = Field(default=0, ge=0)
    retry_count: int = Field(default=0, ge=0, le=2, strict=True)
    retry_budget: int = Field(default=0, ge=0, le=2, strict=True)
    usage: dict[str, int | None] = Field(default_factory=dict)
    error: str | None = None

    @field_validator("run_id")
    @classmethod
    def canonical_uuid(cls, value):
        if str(UUID(value)) != value:
            raise ValueError("A canonical UUID is required.")
        return value

    @model_validator(mode="after")
    def completed_requires_review(self):
        if self.revision_count > self.max_revisions or self.retry_count > self.retry_budget:
            raise ValueError("Revision and retry counts cannot exceed their independent limits.")
        if self.status == "completed" and (
            self.requirements is None
            or self.outline is None
            or self.data_result is None
            or self.data_result.status != "ready"
            or self.data_result.data.status != "ok"
            or self.draft is None
            or self.review is None
            or not self.review.passed
        ):
            raise ValueError("Completed workflows require data, draft and passed review.")
        if self.status == "completed" and (
            len(self.revision_history) != self.revision_count + 1
            or [record.revision_index for record in self.revision_history]
            != list(range(self.revision_count + 1))
            or any(
                record.review.passed or record.review.needs_input
                for record in self.revision_history[:-1]
            )
            or self.revision_history[-1].draft != self.draft
            or self.revision_history[-1].review != self.review
        ):
            raise ValueError("Completed workflows require consistent checked draft history.")
        return self
