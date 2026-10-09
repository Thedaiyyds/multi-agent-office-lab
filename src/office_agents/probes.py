"""Live capability probes and a separate deterministic offline graph demonstration."""

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, TypedDict
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError

from office_agents.config import ConfigurationError, Settings
from office_agents.llm import ModelCallError, OpenAICompatibleClient


class ProbeResult(BaseModel):
    name: str
    passed: bool
    detail: str


class RunReport(BaseModel):
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    mode: Literal["live", "offline"]
    status: Literal["passed", "failed"]
    description: str
    probes: list[ProbeResult]
    elapsed_seconds: float = 0.0


class StructuredAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    number: StrictInt
    label: Literal["probe"]


class EchoArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    number: StrictInt = Field(ge=-100, le=100)


def validate_structured_answer(content: str) -> dict[str, Any]:
    try:
        answer = StructuredAnswer.model_validate_json(content)
    except (ValidationError, ValueError):
        raise ModelCallError("Structured output failed local schema validation.") from None
    if answer.number != 7:
        raise ModelCallError("Structured output failed the expected-value check.")
    return answer.model_dump()


def execute_echo_number(arguments: str) -> dict[str, int]:
    try:
        args = EchoArguments.model_validate_json(arguments)
    except (ValidationError, ValueError):
        raise ModelCallError("Tool arguments failed local validation.") from None
    return {"number": args.number}


def _message(response: dict[str, Any]) -> dict[str, Any]:
    try:
        message = response["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        raise ModelCallError("Model response is missing a completion message.") from None
    if not isinstance(message, dict):
        raise ModelCallError("Model response has an invalid completion message.")
    return message


def _content(response: dict[str, Any]) -> str:
    message = _message(response)
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ModelCallError("Model response has no nonempty text content.")
    return content


def _text_probe(client: OpenAICompatibleClient) -> str:
    _content(client.chat([{"role": "user", "content": "Reply with a short greeting."}]))
    return "Received nonempty text from a real model endpoint; response text is not stored."


def _json_probe(client: OpenAICompatibleClient) -> str:
    response = client.chat(
        [{"role": "user", "content": 'Return exactly {"number":7,"label":"probe"}.'}],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "capability_probe",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "number": {"type": "integer"},
                        "label": {"type": "string", "enum": ["probe"]},
                    },
                    "required": ["number", "label"],
                    "additionalProperties": False,
                },
            },
        },
    )
    validate_structured_answer(_content(response))
    return "Requested json_schema output and locally validated number=7 and label=probe."


def _tool_probe(client: OpenAICompatibleClient) -> str:
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": "Call echo_number with number 7, then report the tool result."}
    ]
    tools = [
        {
            "type": "function",
            "function": {
                "name": "echo_number",
                "description": "Echo a bounded integer for a capability check.",
                "parameters": {
                    "type": "object",
                    "properties": {"number": {"type": "integer", "minimum": -100, "maximum": 100}},
                    "required": ["number"],
                    "additionalProperties": False,
                },
            },
        }
    ]
    response = client.chat(
        messages,
        tools=tools,
        tool_choice={"type": "function", "function": {"name": "echo_number"}},
        parallel_tool_calls=False,
    )
    message = _message(response)
    calls = message.get("tool_calls")
    if not isinstance(calls, list) or len(calls) != 1 or not isinstance(calls[0], dict):
        raise ModelCallError("Model did not return exactly one tool call.")
    call = calls[0]
    function = call.get("function")
    if (
        call.get("type") != "function"
        or not isinstance(call.get("id"), str)
        or not call["id"]
        or not isinstance(function, dict)
        or function.get("name") != "echo_number"
        or not isinstance(function.get("arguments"), str)
    ):
        raise ModelCallError("Model returned an unsupported or malformed tool call.")
    result = execute_echo_number(function["arguments"])
    if result["number"] != 7:
        raise ModelCallError("Tool call failed the expected-value check.")
    messages.extend(
        [
            {"role": "assistant", "content": None, "tool_calls": [call]},
            {"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result)},
        ]
    )
    _content(client.chat(messages, tools=tools, tool_choice="none"))
    return "Validated a forced echo_number call, executed it locally and returned its result."


def run_live_smoke(settings: Settings, *, client_factory=OpenAICompatibleClient) -> RunReport:
    start = time.monotonic()
    probes: list[ProbeResult] = []
    client = None
    try:
        settings.validate_for_live()
        client = client_factory(settings)
        for name, probe in (
            ("text", _text_probe),
            ("structured_json", _json_probe),
            ("tool_call", _tool_probe),
        ):
            try:
                detail = probe(client)
            except ModelCallError as exc:
                probes.append(ProbeResult(name=name, passed=False, detail=str(exc)))
            except Exception:
                probes.append(
                    ProbeResult(name=name, passed=False, detail="Probe execution failed.")
                )
            else:
                probes.append(ProbeResult(name=name, passed=True, detail=detail))
    except ConfigurationError as exc:
        probes.append(ProbeResult(name="configuration", passed=False, detail=str(exc)))
    except Exception:
        probes.append(
            ProbeResult(name="connection_setup", passed=False, detail="Client setup failed.")
        )
    finally:
        if client is not None:
            client.close()
    return RunReport(
        mode="live",
        status="passed" if probes and all(p.passed for p in probes) else "failed",
        description="Live endpoint capability checks; no business agents are implemented in v0.1.",
        probes=probes,
        elapsed_seconds=round(time.monotonic() - start, 3),
    )


class DemoState(TypedDict):
    value: int
    steps: list[str]


def run_graph_demo() -> RunReport:
    from langgraph.graph import END, START, StateGraph

    def increment(state: DemoState) -> DemoState:
        return {"value": state["value"] + 1, "steps": [*state["steps"], "increment"]}

    def double(state: DemoState) -> DemoState:
        return {"value": state["value"] * 2, "steps": [*state["steps"], "double"]}

    start = time.monotonic()
    builder = StateGraph(DemoState)
    builder.add_node("increment", increment)
    builder.add_node("double", double)
    builder.add_edge(START, "increment")
    builder.add_edge("increment", "double")
    builder.add_edge("double", END)
    result = builder.compile().invoke({"value": 2, "steps": []})
    passed = result == {"value": 6, "steps": ["increment", "double"]}
    return RunReport(
        mode="offline",
        status="passed" if passed else "failed",
        description="Deterministic two-node LangGraph check; no model or real multi-agent work.",
        probes=[
            ProbeResult(
                name="two_node_graph",
                passed=passed,
                detail="Expected sequence: increment then double; input 2 becomes 6.",
            )
        ],
        elapsed_seconds=round(time.monotonic() - start, 3),
    )


def save_report(report: RunReport, output_dir: str | Path) -> Path:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{report.mode}-{report.run_id}.json"
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return path
