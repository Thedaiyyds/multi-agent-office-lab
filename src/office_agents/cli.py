"""Small CLI. Diagnostic output never includes endpoint bodies or credentials."""

import argparse
from pathlib import Path

from office_agents.config import ConfigurationError, Settings
from office_agents.probes import ProbeResult, RunReport, run_graph_demo, run_live_smoke, save_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="office-agents")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="Check configuration locally without making model requests.")
    for name in ("smoke", "graph-demo"):
        command = commands.add_parser(name)
        command.add_argument("--output-dir", type=Path, default=Path("outputs"))
        if name == "smoke":
            command.add_argument("--profile", choices=("generic", "deepseek"), default="generic")
    args = parser.parse_args(argv)
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
