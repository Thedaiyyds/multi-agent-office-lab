"""UI-independent contracts for bounded uploads and per-session background runs."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import Field

from office_agents.schemas import ContractModel
from office_agents.workflow_schemas import WorkflowEvent, WorkflowResult

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_ROOT = PROJECT_ROOT / "data" / "samples"
WEB_OUTPUT_ROOT = PROJECT_ROOT / "outputs" / "web"


@dataclass(frozen=True)
class UploadBlob:
    name: str
    content: bytes


@dataclass(frozen=True)
class PreparedInput:
    files: tuple[UploadBlob, ...]
    data_origin: Literal["simulated", "provided"]


class WebRunOptions(ContractModel):
    request: str = Field(min_length=1, max_length=4000)
    mode: Literal["mock", "live"] = "mock"
    max_revisions: int = Field(default=2, ge=0, le=2, strict=True)
    retry_budget: int = Field(default=0, ge=0, le=2, strict=True)
    max_requests: int = Field(default=10, ge=1, le=12, strict=True)
    max_output_tokens: int = Field(default=4032, ge=1, le=5568, strict=True)
    timeout_seconds: float = Field(default=30, gt=0, le=300, allow_inf_nan=False)
    test_scenario: Literal["none", "bad-fact", "missing-section", "always-bad"] = "none"


@dataclass(frozen=True)
class DownloadArtifact:
    name: str
    data: bytes
    mime: str


@dataclass(frozen=True)
class JobSnapshot:
    run_id: str
    status: Literal["queued", "running", "completed", "needs_input", "review_failed", "failed"]
    events: tuple[WorkflowEvent, ...] = ()
    result: WorkflowResult | None = None
    error: str | None = None
    artifact_dir: Path | None = None
    downloads: tuple[DownloadArtifact, ...] = ()
