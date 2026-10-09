"""All capability responses below are mocked and are not live acceptance evidence."""

import json

import httpx
import pytest

from office_agents.config import Settings
from office_agents.llm import ModelCallError, OpenAICompatibleClient
from office_agents.probes import (
    execute_echo_number,
    run_graph_demo,
    run_live_smoke,
    save_report,
    validate_structured_answer,
)


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        '{"number":"7","label":"probe"}',
        '{"number":true,"label":"probe"}',
        '{"number":7.0,"label":"probe"}',
        '{"number":8,"label":"probe"}',
        '{"number":7,"label":"other"}',
        '{"number":7,"label":"probe","extra":"secret-test-key"}',
    ],
)
def test_structured_probe_rejects_wrong_shape_type_and_value(content):
    with pytest.raises(ModelCallError) as error:
        validate_structured_answer(content)
    assert content not in str(error.value)
    assert "secret-test-key" not in str(error.value)


def test_structured_probe_accepts_exact_value():
    assert validate_structured_answer('{"number":7,"label":"probe"}') == {
        "number": 7,
        "label": "probe",
    }


@pytest.mark.parametrize("number", [-100, 7, 100])
def test_echo_tool_accepts_bounded_integer(number):
    assert execute_echo_number(json.dumps({"number": number})) == {"number": number}


@pytest.mark.parametrize(
    "arguments",
    [
        "not json",
        "{}",
        '{"number":true}',
        '{"number":"7"}',
        '{"number":101}',
        '{"number":-101}',
        '{"number":7,"extra":"secret-test-key"}',
    ],
)
def test_echo_tool_rejects_unsafe_arguments(arguments):
    with pytest.raises(ModelCallError) as error:
        execute_echo_number(arguments)
    assert "secret-test-key" not in str(error.value)


def completion(message):
    return {"choices": [{"message": message}]}


def run_mock_smoke(tool_call=None, json_content='{"number":7,"label":"probe"}'):
    requests = []
    call = (
        tool_call
        if tool_call is not None
        else {
            "id": "call-test",
            "type": "function",
            "function": {"name": "echo_number", "arguments": '{"number":7}'},
        }
    )

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        if "response_format" in body:
            message = {"content": json_content}
        elif body.get("tool_choice") == "none":
            message = {"content": "Tool returned 7"}
        elif "tools" in body:
            message = {"content": None, "tool_calls": [call]}
        else:
            message = {"content": "secret-test-key provider text must not be logged"}
        return httpx.Response(200, json=completion(message))

    def factory(settings):
        return OpenAICompatibleClient(settings, transport=httpx.MockTransport(respond))

    report = run_live_smoke(
        Settings(base_url="https://model.invalid/v1", model="test", api_key="secret-test-key"),
        client_factory=factory,
    )
    return report, requests


def test_mock_smoke_checks_schema_and_completes_tool_round_trip():
    report, requests = run_mock_smoke()
    assert report.status == "passed"
    assert [probe.name for probe in report.probes] == ["text", "structured_json", "tool_call"]
    assert len(requests) == 4
    assert requests[1]["response_format"]["type"] == "json_schema"
    assert requests[2]["tool_choice"]["function"]["name"] == "echo_number"
    assert requests[3]["messages"][-1] == {
        "role": "tool",
        "tool_call_id": "call-test",
        "content": '{"number": 7}',
    }
    assert requests[3]["tool_choice"] == "none"
    assert "secret-test-key" not in report.model_dump_json()
    # The production function labels its configured mode live. This mocked invocation
    # is test-only and must never be archived as evidence of real provider success.


@pytest.mark.parametrize(
    "call",
    [
        {
            "id": "call",
            "type": "function",
            "function": {"name": "delete_files", "arguments": '{"number":7}'},
        },
        {
            "id": "call",
            "type": "function",
            "function": {"name": "echo_number", "arguments": '{"number":8}'},
        },
        {
            "id": "",
            "type": "function",
            "function": {"name": "echo_number", "arguments": '{"number":7}'},
        },
        {
            "id": "call",
            "type": "function",
            "function": {"name": "echo_number", "arguments": {"number": 7}},
        },
    ],
)
def test_mock_smoke_rejects_bad_tool_calls_without_sending_tool_result(call):
    report, requests = run_mock_smoke(tool_call=call)
    assert report.status == "failed"
    assert report.probes[-1].name == "tool_call"
    assert report.probes[-1].passed is False
    assert len(requests) == 3


def test_failed_structured_probe_is_not_hidden_by_other_successes():
    report, _ = run_mock_smoke(json_content='{"number":9,"label":"probe"}')
    assert report.status == "failed"
    assert [probe.passed for probe in report.probes] == [True, False, True]


def test_missing_configuration_does_not_create_client():
    def factory(_):
        pytest.fail("Missing configuration must not initiate HTTP or create a client")

    report = run_live_smoke(Settings(), client_factory=factory)
    assert report.status == "failed"
    assert report.probes[0].name == "configuration"


def test_offline_graph_and_saved_reports_are_distinct(tmp_path):
    first = run_graph_demo()
    second = run_graph_demo()
    assert first.mode == "offline"
    assert first.status == second.status == "passed"
    assert first.run_id != second.run_id
    first_path = save_report(first, tmp_path)
    second_path = save_report(second, tmp_path)
    assert first_path != second_path
    assert json.loads(first_path.read_text())["mode"] == "offline"
