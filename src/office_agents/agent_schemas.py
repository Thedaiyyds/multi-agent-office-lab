"""Shared typed contracts for independent role agents."""

from typing import Any, Literal

from pydantic import Field, StrictBool, StrictFloat, StrictInt, model_validator

from office_agents.schemas import ContractModel, DataRequest, DataResult

Role = Literal["manager", "planner", "data", "writer", "checker"]
MetricId = Literal[
    "project_count", "completed_project_count", "completion_rate", "achievement_count"
]
METRIC_IDS = ("project_count", "completed_project_count", "completion_rate", "achievement_count")
DEFAULT_SECTIONS = ["工作概况", "主要成果", "问题与风险", "后续计划"]


class Requirements(DataRequest):
    required_sections: list[str] = Field(min_length=1, max_length=6)
    output_format: Literal["markdown"] = "markdown"

    @model_validator(mode="after")
    def valid_sections(self):
        if any(not section.strip() or len(section) > 48 for section in self.required_sections):
            raise ValueError("Section titles must be nonempty and at most 48 characters.")
        self.required_sections = [section.strip() for section in self.required_sections]
        if len(set(self.required_sections)) != len(self.required_sections):
            raise ValueError("Section titles must be unique.")
        return self


class ManagerDecision(ContractModel):
    status: Literal["ready", "needs_input"]
    requirements: Requirements | None = None
    missing_fields: list[Literal["department", "date_range"]] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def consistent_decision(self):
        if self.status == "ready":
            if self.requirements is None or self.missing_fields or self.questions:
                raise ValueError("Ready decisions require complete requirements only.")
        elif self.requirements is not None or not self.missing_fields or not self.questions:
            raise ValueError("Missing information requires fields and questions.")
        return self


class OutlineSection(ContractModel):
    section_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,23}$")
    title: str = Field(min_length=1, max_length=48)
    purpose: str = Field(min_length=1, max_length=200)
    metric_ids: list[MetricId] = Field(default_factory=list, max_length=4)


class Outline(ContractModel):
    sections: list[OutlineSection] = Field(min_length=1, max_length=6)

    @model_validator(mode="after")
    def unique_sections(self):
        ids = [section.section_id for section in self.sections]
        titles = [section.title for section in self.sections]
        if len(ids) != len(set(ids)) or len(titles) != len(set(titles)):
            raise ValueError("Outline section identities must be unique.")
        if any(
            len(section.metric_ids) != len(set(section.metric_ids)) for section in self.sections
        ):
            raise ValueError("Section metric IDs must be unique.")
        return self


class DataToolArguments(ContractModel):
    department: str = Field(min_length=1)
    start_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


class DataSummary(ContractModel):
    summary: str = Field(min_length=1, max_length=800)
    limitations: list[str] = Field(default_factory=list, max_length=4)


class DataAgentResult(DataSummary):
    status: Literal["ready", "needs_input"]
    data: DataResult


class DraftSection(ContractModel):
    section_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,23}$")
    title: str = Field(min_length=1, max_length=48)
    text: str = Field(min_length=1, max_length=500)


class FactClaim(ContractModel):
    section_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,23}$")
    metric_id: MetricId
    value: StrictInt | StrictFloat | None
    unit: Literal["count", "ratio"]
    source_ids: list[str] = Field(min_length=1, max_length=3)


class Suggestion(ContractModel):
    section_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,23}$")
    text: str = Field(min_length=1, max_length=300)


class DraftContent(ContractModel):
    sections: list[DraftSection] = Field(min_length=1, max_length=6)
    fact_claims: list[FactClaim] = Field(default_factory=list, max_length=8)
    suggestions: list[Suggestion] = Field(default_factory=list, max_length=6)
    issue_scope: Literal["unfiltered"] = "unfiltered"


class Draft(DraftContent):
    markdown: str = Field(min_length=1, max_length=12000)


class ReviewIssue(ContractModel):
    code: str = Field(min_length=1, max_length=64)
    location: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=600)
    severity: Literal["error", "warning"] = "error"


class Review(ContractModel):
    passed: StrictBool
    issues: list[ReviewIssue] = Field(default_factory=list, max_length=32)
    revision_instructions: list[str] = Field(default_factory=list, max_length=32)
    needs_input: StrictBool = False

    @model_validator(mode="after")
    def valid_pass(self):
        if self.passed and (self.needs_input or any(i.severity == "error" for i in self.issues)):
            raise ValueError("Passed reviews cannot contain errors or require input.")
        if not self.passed and not (self.issues or self.revision_instructions or self.needs_input):
            raise ValueError("Rejected reviews require actionable details.")
        return self


class AgentEvent(ContractModel):
    role: Role
    event_type: Literal["model_request", "tool_execution"]
    status: Literal["passed", "failed"]
    created_at: str
    summary: str
    tool_name: str | None = None
    arguments: dict[str, Any] | None = None


class RoleRun(ContractModel):
    role: Role
    status: Literal["passed", "needs_input", "review_failed", "failed"]
    output: dict[str, Any] | None = None
    error: str | None = None
