"""Reproducible release acceptance using actual graphs and local HTTP fixtures.

Expected values come from the sample's independent hand calculation, not from
the metric implementation. A deliberately stopped case passes only if its
actual stopping point, audit, and absence of a final report also match.
"""

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import httpx

from office_agents.agent_runtime import AgentSession
from office_agents.config import Settings
from office_agents.web_schemas import PROJECT_ROOT, PreparedInput, UploadBlob
from office_agents.web_uploads import WebInputError, prepare_input, write_prepared
from office_agents.workflow import run_workflow
from office_agents.workflow_examples import workflow_mock_response
from office_agents.workflow_export import save_workflow
from office_agents.workflow_schemas import WorkflowResult


class AcceptanceError(RuntimeError):
    """Release output failure with fixed diagnostics and no private exception text."""


_Q2 = {
    "project_count": 3,
    "completed_project_count": 2,
    "completion_rate": 2 / 3,
    "achievement_count": 2,
}


@dataclass(frozen=True)
class _Case:
    case_id: str
    request: str
    expected_status: str
    http_requests: int
    revisions: int = 0
    scenario: str = "none"
    department: str | None = None
    start: str | None = None
    end: str | None = None
    metrics: dict | None = None
    refs: tuple[tuple[int, ...], ...] = ()


_CASES = (
    _Case(
        "research-q2",
        "生成研发部2026年第二季度工作报告",
        "completed",
        6,
        department="研发部",
        start="2026-04-01",
        end="2026-07-01",
        metrics=_Q2,
        refs=((3, 4, 5), (3, 4), (3, 4, 5), (2, 3)),
    ),
    _Case(
        "research-q1",
        "生成研发部2026年第一季度工作报告",
        "completed",
        6,
        department="研发部",
        start="2026-01-01",
        end="2026-04-01",
        metrics={
            "project_count": 2,
            "completed_project_count": 1,
            "completion_rate": 0.5,
            "achievement_count": 1,
        },
        refs=((6, 7), (7,), (6, 7), (4,)),
    ),
    _Case(
        "marketing-q2",
        "生成市场部2026年第二季度工作报告",
        "completed",
        6,
        department="市场部",
        start="2026-04-01",
        end="2026-07-01",
        metrics={
            "project_count": 1,
            "completed_project_count": 0,
            "completion_rate": 0,
            "achievement_count": 1,
        },
        refs=((8,), (), (8,), (5,)),
    ),
    _Case("invalid-upload", "", "input_rejected", 0),
    _Case("missing-request", "请生成工作报告", "needs_input", 1),
    _Case(
        "bad-fact-repair",
        "生成研发部2026年第二季度工作报告",
        "completed",
        7,
        revisions=1,
        scenario="bad-fact",
        department="研发部",
        start="2026-04-01",
        end="2026-07-01",
        metrics=_Q2,
        refs=((3, 4, 5), (3, 4), (3, 4, 5), (2, 3)),
    ),
    _Case(
        "persistent-error-limit",
        "生成研发部2026年第二季度工作报告",
        "review_failed",
        7,
        revisions=2,
        scenario="always-bad",
        department="研发部",
        start="2026-04-01",
        end="2026-07-01",
        metrics=_Q2,
        refs=((3, 4, 5), (3, 4), (3, 4, 5), (2, 3)),
    ),
    _Case("model-timeout", "生成研发部2026年第二季度工作报告", "failed", 1),
)


def _json_write(path: Path, value: dict) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def _source_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        value = result.stdout.strip()
        if result.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}", value):
            return value
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def _source_dirty() -> bool | None:
    """Record the local Git worktree state without storing filenames or stderr."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=normal"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if result.returncode == 0:
            return bool(result.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def _case_summary(case: _Case) -> dict:
    return {
        "case_id": case.case_id,
        "status": "failed",
        "expected_status": case.expected_status,
        "passed": False,
        "http_requests": 0,
        "revision_count": 0,
        "metrics": {},
        "run_id": None,
        "artifact_dir": None,
        "diagnostics": [],
    }


def _rejected_upload(case: _Case, suite: Path, prepared: PreparedInput) -> dict:
    summary = _case_summary(case)
    # The entire modified input stays in immutable bytes and isolated validation
    # directories. The real upload validator decides whether admission is refused.
    invalid = tuple(
        UploadBlob(blob.name, "project_id,department\nP001,研发部\n".encode())
        if blob.name == "projects.csv"
        else blob
        for blob in prepared.files
    )
    try:
        prepare_input(invalid)
    except WebInputError as error:
        codes = sorted({issue.code for issue in error.issues if issue.severity == "error"})
        summary["status"] = "input_rejected"
        summary["passed"] = codes == ["invalid_headers"]
        summary["diagnostics"] = [] if summary["passed"] else ["unexpected_input_rejection"]
        directory = suite / case.case_id
        directory.mkdir(exist_ok=False)
        _json_write(
            directory / "input-validation.json",
            {"status": "input_rejected", "issue_codes": codes, "http_requests": 0, "run_id": None},
        )
        summary["artifact_dir"] = case.case_id
    else:
        summary["status"] = "input_accepted"
        summary["diagnostics"] = ["invalid_upload_was_admitted"]
    return summary


def _result_checks(
    case: _Case,
    result: WorkflowResult,
    directory: Path,
    prepared: PreparedInput,
    transport_requests: int,
) -> dict[str, bool]:
    roles = [node.role for node in result.nodes]
    model_events = [event for event in result.events if event.event_type == "model_request"]
    checks = {
        "terminal_status": result.status == case.expected_status,
        "offline_mode": result.mode == "offline_mock" and result.data_origin == "simulated",
        "http_count": result.request_count == case.http_requests == transport_requests,
        "bounded_budget": result.request_count <= 10 and result.reserved_output_tokens <= 4032,
        "no_network_retries": result.retry_budget == result.retry_count == 0,
        "revision_count": result.revision_count == case.revisions and result.max_revisions == 2,
        "actual_request_audit": len(model_events) == result.request_count
        and sum(event.max_output_tokens or 0 for event in model_events)
        == result.reserved_output_tokens,
        "final_report_gate": (directory / "report.md").is_file()
        == (case.expected_status == "completed"),
        "saved_result_matches": json.loads((directory / "run.json").read_text("utf-8"))
        == result.model_dump(mode="json"),
        "saved_events_match": [
            json.loads(line)
            for line in (directory / "events.jsonl").read_text("utf-8").splitlines()
        ]
        == [event.model_dump(mode="json") for event in result.events],
    }
    if case.metrics is not None:
        actual_metrics = {metric.metric_id: metric.value for metric in result.metrics}
        requirements = result.requirements
        checks["hand_calculated_metrics"] = actual_metrics == case.metrics
        checks["request_scope"] = requirements is not None and (
            requirements.department,
            str(requirements.start_date),
            str(requirements.end_date),
        ) == (case.department, case.start, case.end)
        hashes = {blob.name: hashlib.sha256(blob.content).hexdigest() for blob in prepared.files}
        checks["input_hashes"] = {
            source.source_id: source.sha256 for source in result.sources
        } == hashes
        expected_refs = {
            metric_id: [
                ("achievements.csv" if metric_id == "achievement_count" else "projects.csv", line)
                for line in lines
            ]
            for metric_id, lines in zip(_Q2, case.refs, strict=True)
        }
        checks["physical_source_lines"] = {
            metric.metric_id: [(ref.source_id, ref.line_number) for ref in metric.source_refs]
            for metric in result.metrics
        } == expected_refs
        checks["node_sequence"] = roles == ["manager", "planner", "data"] + [
            "writer",
            "checker",
        ] * (case.revisions + 1)
        checks["review_history"] = len(result.revision_history) == case.revisions + 1 and [
            record.review.passed for record in result.revision_history
        ] == (
            [False] * case.revisions + [True]
            if case.expected_status == "completed"
            else [False] * (case.revisions + 1)
        )
        checks["exported_reviews"] = all(
            json.loads(
                (
                    directory / "revisions" / f"{record.revision_index:02d}" / "review.json"
                ).read_text("utf-8")
            )
            == record.review.model_dump(mode="json")
            for record in result.revision_history
        )
        if case.scenario != "none":
            checks["local_fact_rejection"] = all(
                any(issue.code == "fact_value" for issue in record.review.issues)
                and record.review_mode == "program_only"
                for record in result.revision_history
                if not record.review.passed
            )
            checks["injection_audit"] = len(
                [event for event in result.events if event.event_type == "error_injected"]
            ) == (1 if case.scenario == "bad-fact" else 3)
    elif case.case_id == "missing-request":
        decision = result.manager_decision
        checks["manager_needs_input"] = (
            roles == ["manager"]
            and decision is not None
            and decision.status == "needs_input"
            and bool(decision.questions)
            and set(decision.missing_fields) == {"department", "date_range"}
        )
        checks["no_downstream_outputs"] = (
            not result.metrics
            and result.draft is None
            and result.review is None
            and not result.revision_history
        )
    elif case.case_id == "model-timeout":
        checks["timeout_stops_manager"] = (
            roles == ["manager"]
            and result.nodes[0].status == "failed"
            and result.manager_decision is None
        )
        checks["timeout_failed_request"] = (
            len(model_events) == 1 and model_events[0].status == "failed"
        )
        checks["no_downstream_outputs"] = (
            not result.metrics
            and result.draft is None
            and result.review is None
            and not result.revision_history
        )
    return checks


def _graph_case(case: _Case, suite: Path, prepared: PreparedInput) -> dict:
    summary = _case_summary(case)
    session = None
    transport_requests = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal transport_requests
        transport_requests += 1
        if case.case_id == "model-timeout":
            raise httpx.ReadTimeout("Deliberate local timeout fixture", request=request)
        return workflow_mock_response(request)

    try:
        session = AgentSession(
            Settings(base_url="https://mock.invalid", model="release-acceptance-fixture"),
            mode="offline_mock",
            max_requests=10,
            max_total_output_tokens=4032,
            retry_budget=0,
            transport=httpx.MockTransport(respond),
        )
        with TemporaryDirectory(prefix="office-acceptance-input-") as temporary:
            write_prepared(prepared, Path(temporary))
            result = run_workflow(
                case.request,
                Path(temporary),
                session,
                data_origin="simulated",
                max_revisions=2,
                test_scenario=case.scenario,
            )
        summary.update(
            status=result.status,
            run_id=result.run_id,
            http_requests=result.request_count,
            revision_count=result.revision_count,
            metrics={metric.metric_id: metric.value for metric in result.metrics},
        )
        directory = save_workflow(result, suite / "runs")
        summary["artifact_dir"] = directory.relative_to(suite).as_posix()
        checks = _result_checks(case, result, directory, prepared, transport_requests)
        summary["passed"] = all(checks.values())
        summary["diagnostics"] = [key for key, passed in checks.items() if not passed]
    except Exception:
        summary["passed"] = False
        summary["http_requests"] = transport_requests
        summary["diagnostics"] = ["case_execution_or_export_failed"]
    finally:
        if session is not None:
            try:
                session.close()
            except Exception:
                summary["passed"] = False
                summary["diagnostics"].append("session_close_failed")
    return summary


def run_acceptance(output_root: Path) -> tuple[dict, Path]:
    """Run eight bounded, offline release cases and save a unique summary.json.

    Model settings are explicitly constructed; this entry point never loads .env
    or contacts a provider. Paths and exception bodies are excluded from errors.
    """
    suite_id = str(uuid4())
    try:
        root = Path(output_root)
        if root.is_symlink():
            raise ValueError
        root.mkdir(parents=True, exist_ok=True)
        suite = root / suite_id
        suite.mkdir(exist_ok=False)
    except (OSError, TypeError, ValueError):
        raise AcceptanceError("Acceptance output directory could not be created.") from None
    cases = []
    for case in _CASES:
        try:
            prepared = prepare_input(use_samples=True)
            summary = (
                _rejected_upload(case, suite, prepared)
                if case.case_id == "invalid-upload"
                else _graph_case(case, suite, prepared)
            )
        except Exception:
            summary = _case_summary(case)
            summary["diagnostics"] = ["case_input_or_storage_failed"]
        cases.append(summary)
    result = {
        "schema_version": "1.0",
        "suite_id": suite_id,
        "created_at": datetime.now(UTC).isoformat(),
        "mode": "offline_mock",
        "source_commit": _source_commit(),
        "source_dirty": _source_dirty(),
        "passed": all(case["passed"] for case in cases),
        "external_api_requests": 0,
        "cases": cases,
    }
    index = suite / "summary.json"
    try:
        _json_write(index, result)
    except (OSError, TypeError, ValueError):
        raise AcceptanceError("Acceptance summary could not be saved.") from None
    return result, index
