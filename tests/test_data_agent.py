"""Offline boundary tests using actual deterministic sample data."""

import copy
import json
from pathlib import Path

import httpx
import pytest

from office_agents.agent_runtime import AgentSession
from office_agents.agent_schemas import DEFAULT_SECTIONS, Requirements
from office_agents.agents.data import run_data_agent
from office_agents.config import Settings
from office_agents.llm import ModelCallError

SAMPLES = Path(__file__).resolve().parents[1] / "data" / "samples"
ARGS = {"department": "研发部", "start_date": "2026-04-01", "end_date": "2026-07-01"}


def requirements(**updates):
    return Requirements(**(ARGS | {"required_sections": DEFAULT_SECTIONS} | updates))


def completion(message, finish="stop"):
    return {"choices": [{"finish_reason": finish, "message": message}]}


def tool_response(arguments=None, name="run_data_tools", call_id="call_1"):
    if arguments is None:
        arguments = ARGS
    return completion(
        {
            "content": "discard-this-untrusted-assistant-prose",
            "reasoning_content": "discard-hidden-reasoning",
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": json.dumps(arguments, ensure_ascii=False),
                    },
                }
            ],
        },
        "tool_calls",
    )


def summary_response(content=None):
    if content is None:
        content = json.dumps({"summary": "已完成统计。", "limitations": ["问题材料未筛选。"]})
    return completion({"content": content})


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.events = []

    def chat(self, role, messages, *, max_output_tokens, **options):
        self.calls.append(
            {
                "role": role,
                "messages": copy.deepcopy(messages),
                "max_output_tokens": max_output_tokens,
                "options": copy.deepcopy(options),
            }
        )
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def record_tool(self, role, tool_name, arguments, status, summary):
        self.events.append(
            {
                "role": role,
                "tool_name": tool_name,
                "arguments": arguments,
                "status": status,
                "summary": summary,
            }
        )


def test_real_sample_statistics_and_roundtrip_are_authoritative_and_sanitized():
    session = FakeSession([tool_response(), summary_response()])
    result = run_data_agent(requirements(data_origin="simulated"), SAMPLES, session)
    assert result.status == "ready"
    assert result.data.request.data_origin == "simulated"
    assert result.data.request.model_dump(mode="json") == ARGS | {"data_origin": "simulated"}
    assert {metric.metric_id: metric.value for metric in result.data.metrics} == {
        "project_count": 3,
        "completed_project_count": 2,
        "completion_rate": 2 / 3,
        "achievement_count": 2,
    }
    assert [call["max_output_tokens"] for call in session.calls] == [128, 192]
    assert len(session.events) == 1
    assert session.events[0]["arguments"] == ARGS
    assert session.events[0]["status"] == "passed"
    first_options = session.calls[0]["options"]
    assert first_options["tool_choice"]["function"]["name"] == "run_data_tools"
    params = first_options["tools"][0]["function"]["parameters"]
    assert set(params["properties"]) == set(ARGS)
    assert params["additionalProperties"] is False
    second = session.calls[1]
    assert second["options"]["response_format"] == {"type": "json_object"}
    assert second["options"]["tool_choice"] == "none"
    assistant, tool = second["messages"][-2:]
    assert assistant["content"] is None
    assert set(assistant) == {"role", "content", "tool_calls"}
    assert tool["tool_call_id"] == "call_1"
    compact = json.loads(tool["content"])
    assert compact["metrics"][2]["value"] == 2 / 3
    assert compact["metrics"][2]["source_ids"] == ["projects.csv"]
    assert compact["issue_material_scope"] == "unfiltered"
    serialized = json.dumps(second, ensure_ascii=False)
    for forbidden in (str(SAMPLES), "discard-hidden-reasoning", "discard-this", "市场部"):
        assert forbidden not in serialized
    assert "text" not in compact


def test_no_data_remains_ready_with_null_completion_rate():
    args = ARGS | {"department": "财务部"}
    session = FakeSession([tool_response(args), summary_response()])
    result = run_data_agent(requirements(department="财务部"), SAMPLES, session)
    assert result.status == "ready"
    assert result.data.status == "no_data"
    assert result.data.metrics[2].value is None
    compact = json.loads(session.calls[1]["messages"][-1]["content"])
    assert compact["status"] == "no_data"
    assert "no_projects" in compact["issue_codes"]
    assert compact["metrics"][2]["value"] is None


def test_invalid_data_stops_after_one_model_request_and_has_actual_failed_event(tmp_path):
    for source in ("projects.csv", "achievements.csv", "issues.txt"):
        (tmp_path / source).write_bytes((SAMPLES / source).read_bytes())
    with (tmp_path / "projects.csv").open("a", encoding="utf-8") as stream:
        stream.write("INVALID,市场部,2025-01-01,active,nan\n")
    session = FakeSession([tool_response()])
    result = run_data_agent(requirements(), tmp_path, session)
    assert result.status == "needs_input"
    assert result.data.status == "invalid_data"
    assert not result.data.metrics
    assert len(session.calls) == 1
    assert session.events[0]["status"] == "failed"
    assert session.events[0]["arguments"] == ARGS
    assert "修复" in result.summary
    assert str(tmp_path) not in json.dumps(session.events, ensure_ascii=False)


@pytest.mark.parametrize(
    "updates",
    [
        {"department": "市场部"},
        {"department": " 研发部 "},
        {"start_date": "2026-01-01"},
        {"end_date": "2026-10-01"},
        {"start_date": "2026-4-1"},
        {"start_date": "2026-04-31"},
        {"department": True},
        {"data_root": "/unauthorized"},
        {"data_origin": "provided"},
    ],
)
def test_wrong_or_extra_arguments_never_execute_tools(updates, monkeypatch):
    def forbidden(*_args):
        pytest.fail("Unauthorized tool must not execute.")

    monkeypatch.setattr("office_agents.agents.data.run_data_tools", forbidden)
    session = FakeSession([tool_response(ARGS | updates)])
    with pytest.raises(ModelCallError, match="Data Agent"):
        run_data_agent(requirements(), SAMPLES, session)
    assert len(session.calls) == 1
    assert not session.events


@pytest.mark.parametrize("name", ["read_file", "run_data_tools ", "send_email"])
def test_unknown_tools_are_rejected(name):
    session = FakeSession([tool_response(name=name)])
    with pytest.raises(ModelCallError, match="not authorized"):
        run_data_agent(requirements(), SAMPLES, session)
    assert not session.events


@pytest.mark.parametrize("call_id", ["", None, 4, "a\nb", "x" * 129])
def test_invalid_call_identity_is_rejected(call_id):
    session = FakeSession([tool_response(call_id=call_id)])
    with pytest.raises(ModelCallError, match="not authorized"):
        run_data_agent(requirements(), SAMPLES, session)
    assert not session.events


@pytest.mark.parametrize("calls", [[], None, [None], [1, 2]])
def test_missing_invalid_or_multiple_tool_calls_are_rejected(calls):
    session = FakeSession([completion({"tool_calls": calls})])
    with pytest.raises(ModelCallError):
        run_data_agent(requirements(), SAMPLES, session)
    assert not session.events


@pytest.mark.parametrize(
    "arguments",
    [
        "not-json-secret",
        "[]",
        "null",
        "{}",
        "x" * 2001,
        '{"department":"研发部","department":"研发部","start_date":"2026-04-01",'
        '"end_date":"2026-07-01"}',
    ],
)
def test_invalid_and_duplicate_json_arguments_are_rejected_safely(arguments):
    response = tool_response()
    response["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = arguments
    session = FakeSession([response])
    with pytest.raises(ModelCallError, match="arguments are invalid") as error:
        run_data_agent(requirements(), SAMPLES, session)
    assert "secret" not in str(error.value)
    assert not session.events


def test_tool_execution_exception_is_safe_and_not_retried(monkeypatch):
    def broken(*_args):
        raise OSError("private-path-and-secret")

    monkeypatch.setattr("office_agents.agents.data.run_data_tools", broken)
    session = FakeSession([tool_response()])
    with pytest.raises(ModelCallError, match="authorized tool execution failed") as error:
        run_data_agent(requirements(), SAMPLES, session)
    assert "private" not in str(error.value)
    assert len(session.calls) == 1
    assert len(session.events) == 1
    assert session.events[0]["status"] == "failed"


@pytest.mark.parametrize(
    "content",
    ["bad-json-secret", "{}", '{"summary":"","limitations":[]}', '{"summary":"x","path":"x"}'],
)
def test_invalid_summary_fails_after_two_calls_without_retry(content):
    session = FakeSession([tool_response(), summary_response(content)])
    with pytest.raises(ModelCallError, match="summary failed local JSON validation") as error:
        run_data_agent(requirements(), SAMPLES, session)
    assert "secret" not in str(error.value)
    assert len(session.calls) == 2
    assert len(session.events) == 1


@pytest.mark.parametrize(
    "content",
    [
        '{"summary":"private-first","summary":"private-second","limitations":[]}',
        '{"summary":"private","limitations":[NaN]}',
        '{"summary":"private","limitations":[Infinity]}',
        '{"summary":"private","limitations":[-Infinity]}',
        '{"summary":1e999,"limitations":[]}',
    ],
)
def test_ambiguous_or_nonfinite_summary_json_is_rejected_safely(content):
    session = FakeSession([tool_response(), summary_response(content)])
    with pytest.raises(ModelCallError, match="summary failed local JSON validation") as error:
        run_data_agent(requirements(), SAMPLES, session)
    assert "private" not in str(error.value)
    assert len(session.calls) == 2
    assert len(session.events) == 1


def test_summary_cannot_issue_third_tool_request():
    session = FakeSession([tool_response(), tool_response()])
    with pytest.raises(ModelCallError, match="cannot request additional tools"):
        run_data_agent(requirements(), SAMPLES, session)
    assert len(session.calls) == 2


def test_truncated_tool_response_does_not_execute_tool():
    response = tool_response()
    response["choices"][0]["finish_reason"] = "length"
    session = FakeSession([response])
    with pytest.raises(ModelCallError, match="truncated"):
        run_data_agent(requirements(), SAMPLES, session)
    assert not session.events


def test_model_failure_is_not_retried():
    session = FakeSession([ModelCallError("Model request failed.")])
    with pytest.raises(ModelCallError, match="Model request failed"):
        run_data_agent(requirements(), SAMPLES, session)
    assert len(session.calls) == 1
    assert not session.events


def test_actual_session_records_model_tool_model_events_without_external_network():
    responses = [tool_response(), summary_response()]
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=responses.pop(0))

    session = AgentSession(
        Settings(base_url="https://offline.invalid", model="mock", api_key="offline-only"),
        mode="offline_mock",
        transport=httpx.MockTransport(respond),
    )
    try:
        result = run_data_agent(requirements(), SAMPLES, session)
        assert result.status == "ready"
        assert session.request_count == 2
        assert session.reserved_output_tokens == 320
        assert [event.event_type for event in session.events] == [
            "model_request",
            "tool_execution",
            "model_request",
        ]
        assert all(event.role == "data" and event.status == "passed" for event in session.events)
        assert session.events[1].arguments == ARGS
        assert [request["max_tokens"] for request in requests] == [128, 192]
        assert all(request["thinking"] == {"type": "disabled"} for request in requests)
        assert session.client.settings.max_retries == 0
    finally:
        session.close()
