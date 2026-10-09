"""Small CLI. Diagnostic output never includes endpoint bodies or credentials."""

import argparse
from pathlib import Path

from pydantic import ValidationError

from office_agents.config import ConfigurationError, Settings
from office_agents.probes import ProbeResult, RunReport, run_graph_demo, run_live_smoke, save_report
from office_agents.schemas import DataRequest


def _run(args: argparse.Namespace) -> int:
    from office_agents.agent_runtime import AgentSession
    from office_agents.workflow import run_workflow
    from office_agents.workflow_examples import make_workflow_mock_transport
    from office_agents.workflow_export import WorkflowExportError, save_workflow

    session = None
    try:
        try:
            is_sample = args.data_dir.resolve() == Path("data/samples").resolve()
        except (OSError, RuntimeError):
            is_sample = False
        origin = args.data_origin or ("simulated" if is_sample else "provided")
        settings = (
            Settings(base_url="https://mock.invalid", model="scripted-workflow")
            if args.mode == "mock"
            else Settings.from_env()
        )
        session = AgentSession(
            settings,
            profile=args.profile,
            mode="offline_mock" if args.mode == "mock" else "live",
            max_requests=args.max_requests,
            max_total_output_tokens=1984,
            transport=make_workflow_mock_transport() if args.mode == "mock" else None,
        )
        result = run_workflow(args.request, args.data_dir, session, data_origin=origin)
    except ConfigurationError as exc:
        print(f"Workflow configuration failed: {exc}")
        return 1
    except Exception:
        print("Workflow could not start; no final report accepted.")
        return 1
    finally:
        if session is not None:
            session.close()
    print(f"Mode: {result.mode}; status: {result.status}; run_id={result.run_id}.")
    if result.mode == "offline_mock":
        print("Local scripted HTTP fixtures; no real model requests.")
    for node in result.nodes:
        print(f"{node.role}: {node.status}; duration_ms={node.duration_ms:.2f}.")
    if result.manager_decision and result.manager_decision.status == "needs_input":
        for question in result.manager_decision.questions:
            print(question)
    if result.data_result and result.status == "needs_input":
        print(result.data_result.summary)
        for issue in result.data_issues:
            print(f"{issue.severity.upper()} {issue.code}: {issue.message}")
    if result.review and not result.review.passed:
        print("审核未通过；本版不自动返工。")
        for issue in result.review.issues:
            print(f"{issue.code} [{issue.location}]: {issue.message}")
    if result.error:
        print(result.error)
    print(
        f"HTTP requests: {result.request_count}; reserved output limit: "
        f"{result.reserved_output_tokens}."
    )
    for key in ("prompt_tokens", "completion_tokens", "total_tokens", "reasoning_tokens"):
        value = result.usage.get(key)
        print(f"{key}: {value if value is not None else 'unavailable'}")
    try:
        path = save_workflow(result, args.output_dir)
    except WorkflowExportError:
        print("Workflow artifacts could not be saved; no final report accepted.")
        return 1
    print(f"Workflow artifacts: {path}")
    print(
        "Final report: report.md" if result.status == "completed" else "No final report exported."
    )
    return 0 if result.status == "completed" else 1


def _agent_demo(args: argparse.Namespace) -> int:
    from office_agents.agent_examples import (
        make_mock_transport,
        run_role_examples,
        sample_requirements,
    )
    from office_agents.agent_runtime import AgentSession

    session = None
    try:
        try:
            is_sample = args.data_dir.resolve() == Path("data/samples").resolve()
        except (OSError, RuntimeError):
            is_sample = False
        requirements = sample_requirements(
            args.department,
            args.start_date,
            args.end_date,
            args.data_origin or ("simulated" if is_sample else "provided"),
        )
        if args.mode == "mock":
            settings = Settings(base_url="https://mock.invalid", model="scripted-fixture")
            transport = make_mock_transport(requirements, args.data_dir, args.case, args.role)
        else:
            settings = Settings.from_env()
            transport = None
        expected_requests = 6 if args.role == "all" else (2 if args.role == "data" else 1)
        session = AgentSession(
            settings,
            profile=args.profile,
            mode="offline_mock" if args.mode == "mock" else "live",
            max_requests=args.max_requests if args.max_requests is not None else expected_requests,
            transport=transport,
        )
        report = run_role_examples(
            session,
            role=args.role,
            data_root=args.data_dir,
            requirements=requirements,
            case=args.case,
            user_text=args.request,
        )
    except ValidationError:
        print("Invalid agent example request; check department and ordered YYYY-MM-DD dates.")
        return 1
    except ConfigurationError as exc:
        print(f"Agent configuration failed: {exc}")
        return 1
    except Exception:
        print("Agent example could not start; no role result accepted.")
        return 1
    finally:
        if session is not None:
            session.close()
    print(f"Mode: {report.mode}; status: {report.status}.")
    print(report.description)
    for run in report.runs:
        print(f"{run.role}: {run.status}" + (f"; {run.error}" if run.error else ""))
    print(
        f"HTTP requests: {report.request_count}; "
        f"reserved output limit: {report.reserved_output_tokens}."
    )
    if report.mode == "offline_mock":
        print("Scripted local HTTP fixtures; no real model requests or model-generated evidence.")
    for key in ("prompt_tokens", "completion_tokens", "total_tokens", "reasoning_tokens"):
        value = report.usage.get(key)
        print(f"{key}: {value if value is not None else 'unavailable'}")
    try:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / f"agents-{report.run_id}.json").write_text(
            report.model_dump_json(indent=2), encoding="utf-8"
        )
    except OSError:
        print("Agent report could not be saved; check output directory permissions.")
        return 1
    print(f"Agent report saved with run_id={report.run_id}.")
    return 0 if report.status == "passed" else 1


def _data_check(args: argparse.Namespace) -> int:
    """Run deterministic data tools without loading model configuration."""
    from office_agents.tools.metrics import run_data_tools

    origin = args.data_origin
    if origin is None:
        try:
            is_sample = args.data_dir.resolve() == Path("data/samples").resolve()
        except (OSError, RuntimeError):
            is_sample = False
        origin = "simulated" if is_sample else "provided"
    try:
        request = DataRequest(
            department=args.department,
            start_date=args.start_date,
            end_date=args.end_date,
            data_origin=origin,
        )
    except ValidationError:
        print("Invalid data request: provide a department and ordered YYYY-MM-DD dates.")
        return 1
    try:
        result = run_data_tools(args.data_dir, request)
    except Exception:
        print("Data tools could not complete; no metrics were accepted.")
        return 1
    print(f"Mode: {result.mode}; status: {result.status}; data origin: {request.data_origin}.")
    print("Deterministic data tools; no model request or business Agent execution.")
    for metric in result.metrics:
        value = "null" if metric.value is None else str(metric.value)
        print(f"{metric.metric_id}: {value} ({metric.unit})")
    for issue in result.data_issues:
        location = issue.source_id or "dataset"
        if issue.line_number is not None:
            location += f":{issue.line_number}"
        if issue.field is not None:
            location += f":{issue.field}"
        print(f"{issue.severity.upper()} {issue.code} [{location}]: {issue.message}")
    if result.issue_materials:
        print(
            "issues.txt: unfiltered source material; no department/date attribution or issue count."
        )
    try:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        path = args.output_dir / f"data-{result.run_id}.json"
        path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    except OSError:
        print("Data report could not be saved; check output directory permissions.")
        return 1
    print(f"Data report saved with run_id={result.run_id}.")
    return 1 if result.status == "invalid_data" else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="office-agents")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="Check configuration locally without making model requests.")
    run_command = commands.add_parser("run", help="Run the actual five-role LangGraph workflow.")
    run_command.add_argument("--request", required=True)
    run_command.add_argument("--data-dir", type=Path, default=Path("data/samples"))
    run_command.add_argument("--data-origin", choices=("simulated", "provided"))
    run_command.add_argument("--mode", choices=("mock", "live"), default="mock")
    run_command.add_argument("--profile", choices=("deepseek", "generic"), default="deepseek")
    run_command.add_argument("--max-requests", type=int, default=6)
    run_command.add_argument("--output-dir", type=Path, default=Path("outputs"))
    agent_command = commands.add_parser(
        "agent-demo", help="Run independent role examples (mock by default)."
    )
    agent_command.add_argument(
        "--role", choices=("manager", "planner", "data", "writer", "checker", "all"), default="all"
    )
    agent_command.add_argument("--mode", choices=("mock", "live"), default="mock")
    agent_command.add_argument("--profile", choices=("deepseek", "generic"), default="deepseek")
    agent_command.add_argument(
        "--case", choices=("normal", "bad-draft", "missing-requirements"), default="normal"
    )
    agent_command.add_argument("--data-dir", type=Path, default=Path("data/samples"))
    agent_command.add_argument("--department", default="研发部")
    agent_command.add_argument("--start-date", default="2026-04-01")
    agent_command.add_argument("--end-date", default="2026-07-01")
    agent_command.add_argument("--data-origin", choices=("simulated", "provided"))
    agent_command.add_argument(
        "--request", help="Custom natural-language text for the Manager example."
    )
    agent_command.add_argument("--max-requests", type=int)
    agent_command.add_argument("--output-dir", type=Path, default=Path("outputs"))
    data_command = commands.add_parser(
        "data-check", help="Validate and calculate offline data metrics."
    )
    data_command.add_argument("--data-dir", type=Path, default=Path("data/samples"))
    data_command.add_argument("--department", required=True)
    data_command.add_argument("--start-date", required=True)
    data_command.add_argument("--end-date", required=True)
    data_command.add_argument("--data-origin", choices=("simulated", "provided"))
    data_command.add_argument("--output-dir", type=Path, default=Path("outputs"))
    for name in ("smoke", "graph-demo"):
        command = commands.add_parser(name)
        command.add_argument("--output-dir", type=Path, default=Path("outputs"))
        if name == "smoke":
            command.add_argument("--profile", choices=("generic", "deepseek"), default="generic")
    args = parser.parse_args(argv)
    if args.command == "run":
        return _run(args)
    if args.command == "agent-demo":
        return _agent_demo(args)
    if args.command == "data-check":
        return _data_check(args)
    if args.command == "doctor":
        try:
            settings = Settings.from_env()
            settings.validate_for_live()
        except ConfigurationError as exc:
            print(f"Configuration check failed: {exc}")
            return 1
        print("Configuration valid. Address/model are set; credentials are not displayed.")
        print(
            "API key: configured."
            if settings.api_key
            else "API key: absent (local services may allow this)."
        )
        print("No live request made; model capabilities remain unverified.")
        return 0
    if args.command == "graph-demo":
        try:
            report = run_graph_demo()
        except Exception:
            report = RunReport(
                mode="offline",
                status="failed",
                description="Offline LangGraph demonstration; no model or real multi-agent work.",
                probes=[
                    ProbeResult(
                        name="two_node_graph", passed=False, detail="Graph execution failed."
                    )
                ],
            )
    else:
        try:
            report = run_live_smoke(Settings.from_env(), profile=args.profile)
        except ConfigurationError as exc:
            report = RunReport(
                mode="live",
                status="failed",
                description="Live smoke checks could not start.",
                probes=[ProbeResult(name="configuration", passed=False, detail=str(exc))],
                profile=args.profile,
                max_output_tokens=64,
                request_count=0,
            )
    print(f"Mode: {report.mode}; result: {report.status}.")
    print(report.description)
    for probe in report.probes:
        print(f"{'PASS' if probe.passed else 'FAIL'} {probe.name}: {probe.detail}")
    if report.mode == "live":
        print(
            f"Profile: {report.profile}; max output tokens per request: {report.max_output_tokens}."
        )
        count = report.request_count if report.request_count is not None else "unavailable"
        print(f"HTTP requests: {count}.")
        for key in ("prompt_tokens", "completion_tokens", "total_tokens", "reasoning_tokens"):
            value = report.usage.get(key) if report.usage else None
            print(f"{key}: {value if value is not None else 'unavailable'}")
    try:
        save_report(report, args.output_dir)
    except OSError:
        print("Report could not be saved; check output directory permissions.")
        return 1
    print(f"Report saved with run_id={report.run_id}.")
    return 0 if report.status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
