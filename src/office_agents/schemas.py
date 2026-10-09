"""Shared v0.2 contracts for deterministic data tools; no model calls."""

import re
from datetime import UTC, date, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def iso_date(value):
    if type(value) is date:
        return value
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("Use YYYY-MM-DD dates.")
    return date.fromisoformat(value)


class DataRequest(ContractModel):
    department: str = Field(min_length=1)
    start_date: date
    end_date: date
    data_origin: Literal["simulated", "provided"] = "provided"

    _dates = field_validator("start_date", "end_date", mode="before")(iso_date)

    @model_validator(mode="after")
    def ordered_dates(self):
        if self.start_date >= self.end_date:
            raise ValueError("start_date must precede end_date.")
        return self


class SourceRef(ContractModel):
    source_id: str
    line_number: int = Field(ge=1)


class SourceRecord(ContractModel):
    source_id: str
    file_name: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    record_count: int = Field(ge=0)


class DataIssue(ContractModel):
    severity: Literal["error", "warning"]
    code: str
    message: str
    source_id: str | None = None
    line_number: int | None = Field(default=None, ge=1)
    field: str | None = None


class ProjectSnapshot(ContractModel):
    project_id: str = Field(min_length=1)
    department: str = Field(min_length=1)
    snapshot_date: date
    status: Literal["planned", "active", "completed", "blocked"]
    progress: float = Field(ge=0, le=100, allow_inf_nan=False)
    source: SourceRef

    _dates = field_validator("snapshot_date", mode="before")(iso_date)

    @field_validator("progress", mode="before")
    @classmethod
    def no_bool_progress(cls, value):
        if isinstance(value, bool):
            raise ValueError("Progress must be numeric.")
        return value

    @model_validator(mode="after")
    def completed_progress(self):
        if self.status == "completed" and self.progress != 100:
            raise ValueError("Completed projects require progress=100.")
        return self


class Achievement(ContractModel):
    achievement_id: str = Field(min_length=1)
    department: str = Field(min_length=1)
    date: date
    type: str = Field(min_length=1)
    description: str = Field(min_length=1)
    source: SourceRef

    _dates = field_validator("date", mode="before")(iso_date)


class RawRow(ContractModel):
    values: dict[str, str]
    line_number: int = Field(ge=1)


class RawTable(ContractModel):
    source: SourceRecord | None = None
    rows: list[RawRow] = Field(default_factory=list)
    data_issues: list[DataIssue] = Field(default_factory=list)


class IssueMaterial(ContractModel):
    source_id: str = "issues.txt"
    scope: Literal["unfiltered"] = "unfiltered"
    text: str


class ValidatedDataset(ContractModel):
    projects: list[ProjectSnapshot] = Field(default_factory=list)
    achievements: list[Achievement] = Field(default_factory=list)
    issue_materials: list[IssueMaterial] = Field(default_factory=list)
    sources: list[SourceRecord] = Field(default_factory=list)
    data_issues: list[DataIssue] = Field(default_factory=list)


class Metric(ContractModel):
    metric_id: Literal[
        "project_count", "completed_project_count", "completion_rate", "achievement_count"
    ]
    value: int | float | None
    unit: Literal["count", "ratio"]
    definition: str
    source_ids: list[str]
    source_refs: list[SourceRef] = Field(default_factory=list)


class DataResult(ContractModel):
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    mode: Literal["offline"] = "offline"
    status: Literal["ok", "no_data", "invalid_data"]
    request: DataRequest
    metrics: list[Metric] = Field(default_factory=list)
    sources: list[SourceRecord] = Field(default_factory=list)
    data_issues: list[DataIssue] = Field(default_factory=list)
    issue_materials: list[IssueMaterial] = Field(default_factory=list)
