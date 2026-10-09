"""HTTP-attempt budgets, opt-in retry policy and safe audit evidence."""

import json

import httpx
import pytest

from office_agents.agent_runtime import AgentSession
from office_agents.agent_schemas import DataSummary
from office_agents.config import ConfigurationError, Settings
from office_agents.llm import ModelCallError


def reply(content='{"summary":"ok","limitations":[]}'):
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        },
    )


def session_for(handler, **options):
    return AgentSession(
        Settings(base_url="https://mock.invalid", model="fixture", api_key="PRIVATE_KEY"),
        mode="offline_mock",
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
        **options,
    )


@pytest.mark.parametrize("failure", ["timeout", "connect", 429, 500, 503])
def test_transient_recovery_counts_each_attempt_and_unknown_usage(failure):
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        if len(calls) == 1:
            if failure == "timeout":
                raise httpx.ReadTimeout("PRIVATE_KEY PRIVATE_DIAGNOSTIC", request=request)
            if failure == "connect":
                raise httpx.ConnectError("PRIVATE_KEY PRIVATE_DIAGNOSTIC", request=request)
            return httpx.Response(failure, text="PRIVATE_KEY PRIVATE_DIAGNOSTIC")
        return reply()

    session = session_for(handler, retry_budget=1)
    try:
        session.json("data", "JSON", {}, DataSummary, max_output_tokens=192)
        assert session.request_count == 2
        assert session.logical_request_count == 1
        assert session.retry_count == 1
        assert session.reserved_output_tokens == 384
        assert session.usage_statistics["total_tokens"] is None
        assert [e.event_type for e in session.events] == [
            "model_request",
            "model_retry",
            "model_request",
        ]
        assert [e.attempt for e in session.events] == [1, 2, 2]
        assert [e.status for e in session.events] == ["failed", "passed", "passed"]
        assert [e.max_output_tokens for e in session.events] == [192, 192, 192]
        serialized = json.dumps([e.model_dump() for e in session.events])
        assert "PRIVATE_KEY" not in serialized and "PRIVATE_DIAGNOSTIC" not in serialized
        assert calls[0] == calls[1]
        assert calls[0]["thinking"] == {"type": "disabled"}
    finally:
        session.close()


@pytest.mark.parametrize("retry_budget", [0, 1, 2])
def test_global_budget_and_one_retry_per_logical_request(retry_budget):
    session = session_for(lambda _: httpx.Response(503), retry_budget=retry_budget)
    try:
        for _ in range(3):
            with pytest.raises(ModelCallError) as error:
                session.chat("manager", [], max_output_tokens=256)
            assert error.value.code == "service_unavailable"
            assert error.value.retryable is True
        assert session.request_count == 3 + retry_budget
        assert session.logical_request_count == 3
        assert session.retry_count == retry_budget
        assert session.reserved_output_tokens == 256 * (3 + retry_budget)
        attempts = [e.attempt for e in session.events if e.event_type == "model_request"]
        assert attempts.count(1) == 3 and attempts.count(2) == retry_budget
    finally:
        session.close()


@pytest.mark.parametrize(
    "options,code",
    [({"max_requests": 1}, "request_budget"), ({"max_total_output_tokens": 192}, "output_budget")],
)
def test_retry_admission_does_not_exceed_http_or_output_budget(options, code):
    sleeps = []
    session = session_for(lambda _: httpx.Response(503), retry_budget=2, **options)
    session._sleep = sleeps.append
    try:
        with pytest.raises(ModelCallError) as error:
            session.chat("data", [], max_output_tokens=192)
        assert error.value.code == code
        assert error.value.retryable is False
        assert session.request_count == 1
        assert session.retry_count == 0
        assert session.reserved_output_tokens == 192
        assert sleeps == []
        assert len(session.events) == 1
    finally:
        session.close()


@pytest.mark.parametrize("status", [400, 401, 403, 404, 307])
def test_nontransient_http_does_not_retry_or_leak_body(status):
    session = session_for(
        lambda _: httpx.Response(status, text="PRIVATE_KEY PRIVATE_DIAGNOSTIC"), retry_budget=2
    )
    try:
        with pytest.raises(ModelCallError) as error:
            session.chat("manager", [], max_output_tokens=256)
        assert error.value.retryable is False
        assert "PRIVATE" not in str(error.value)
        assert session.request_count == 1 and session.retry_count == 0
    finally:
        session.close()


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="PRIVATE_DIAGNOSTIC"),
        httpx.Response(200, json=[]),
        httpx.Response(200, json={"choices": []}),
        reply("PRIVATE_DIAGNOSTIC"),
        reply('{"summary":"PRIVATE_DIAGNOSTIC","unexpected":1}'),
        reply('{"summary":"x","summary":"PRIVATE_DIAGNOSTIC"}'),
    ],
)
def test_success_status_with_invalid_completion_or_schema_is_not_retried(response):
    session = session_for(lambda _: response, retry_budget=2)
    try:
        with pytest.raises(ModelCallError) as error:
            session.json("data", "JSON", {}, DataSummary, max_output_tokens=192)
        assert error.value.retryable is False
        assert session.request_count == 1 and session.retry_count == 0
        assert session.events[-1].status == "failed"
        assert "PRIVATE" not in str(error.value)
        assert "PRIVATE" not in json.dumps([event.model_dump() for event in session.events])
    finally:
        session.close()


@pytest.mark.parametrize("value", [-1, 3, True, 1.0, "1"])
def test_retry_budget_rejects_noninteger_or_out_of_range_values(value):
    with pytest.raises(ConfigurationError):
        session_for(lambda _: reply(), retry_budget=value)


def test_expanded_hard_budget_is_accepted_and_blocks_thirteenth_attempt():
    session = session_for(lambda _: reply(), max_requests=12, max_total_output_tokens=5568)
    try:
        for _ in range(12):
            session.chat("manager", [], max_output_tokens=256)
        with pytest.raises(ModelCallError, match="request budget"):
            session.chat("manager", [], max_output_tokens=256)
        assert session.request_count == 12
        assert session.usage_statistics["total_tokens"] == 60
    finally:
        session.close()


def test_transport_protocol_failure_is_not_guessed_retryable_from_message():
    def handler(request):
        raise httpx.RemoteProtocolError("timeout PRIVATE_KEY", request=request)

    session = session_for(handler, retry_budget=2)
    try:
        with pytest.raises(ModelCallError) as error:
            session.chat("manager", [], max_output_tokens=256)
        assert error.value.code == "transport" and error.value.retryable is False
        assert session.request_count == 1 and session.retry_count == 0
        assert "PRIVATE_KEY" not in str(error.value)
    finally:
        session.close()


def test_failed_retry_wait_does_not_record_an_attempt_or_spend_its_budget():
    def failed_sleep(_):
        raise RuntimeError("PRIVATE_DIAGNOSTIC")

    session = session_for(lambda _: httpx.Response(503), retry_budget=2)
    session._sleep = failed_sleep
    try:
        with pytest.raises(ModelCallError) as error:
            session.chat("data", [], max_output_tokens=192)
        assert error.value.code == "retry_wait" and "PRIVATE" not in str(error.value)
        assert session.request_count == 1 and session.retry_count == 0
        assert session.reserved_output_tokens == 192
        assert len(session.events) == 1
    finally:
        session.close()


def test_unserializable_options_are_rejected_before_http_and_reservation():
    session = session_for(lambda _: reply(), retry_budget=2)
    try:
        with pytest.raises(ModelCallError) as error:
            session.chat("data", [], max_output_tokens=192, stop=object())
        assert error.value.code == "invalid_parameters" and error.value.retryable is False
        assert session.request_count == 0 and session.retry_count == 0
        assert session.reserved_output_tokens == 0
        assert not session.events
    finally:
        session.close()
