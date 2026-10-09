"""Small CLI. Diagnostic output never includes endpoint bodies or credentials."""

import argparse
from pathlib import Path

from pydantic import ValidationError

from office_agents.config import ConfigurationError, Settings
from office_agents.probes import ProbeResult, RunReport, run_graph_demo, run_live_smoke, save_report
from office_agents.schemas import DataRequest


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
