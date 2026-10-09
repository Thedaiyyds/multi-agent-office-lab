"""Local HTTP transport tests for request budgets and safe role parsing."""

import json

import httpx
import pytest

from office_agents.agent_runtime import AgentSession, parse_json_model, response_message
from office_agents.agent_schemas import DataSummary, FactClaim
from office_agents.config import ConfigurationError, Settings
from office_agents.llm import ModelCallError


def settings():
    return Settings(base_url="https://mock.invalid", model="mock", max_retries=5)


def response(content, **kwargs):
    return httpx.Response(200, json={"choices": [{"message": {"content": content}, **kwargs}]})


def test_budget_and_deepseek_options_are_enforced_before_extra_http():
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return response('{"summary":"fixture","limitations":[]}', finish_reason="stop")

    session = AgentSession(
        settings(), mode="offline_mock", transport=httpx.MockTransport(handler), max_requests=1
    )
    original = [{"role": "system", "content": "JSON"}, {"role": "user", "content": "x"}]
    try:
        session.chat("data", original, max_output_tokens=128)
        with pytest.raises(ModelCallError, match="request budget"):
            session.chat("data", original, max_output_tokens=128)
        assert session.request_count == 1
        assert session.reserved_output_tokens == 128
        assert session.client.settings.max_retries == 0
        assert original[0]["content"] == "JSON"
        assert requests[0]["thinking"] == {"type": "disabled"}
        assert requests[0]["max_tokens"] == 128
        assert requests[0]["temperature"] == 0
        assert requests[0]["messages"][0]["content"].startswith("ROLE=data")
    finally:
        session.close()


def test_output_reservations_block_requests_even_when_previous_reply_was_short():
    session = AgentSession(
        settings(),
        transport=httpx.MockTransport(lambda _: response("OK")),
        max_total_output_tokens=192,
    )
    try:
        session.chat("data", [], max_output_tokens=128)
        with pytest.raises(ModelCallError, match="output budget"):
            session.chat("data", [], max_output_tokens=128)
        assert session.request_count == 1
    finally:
        session.close()


@pytest.mark.parametrize(
    "content",
    [
        '{"summary":"x","summary":"y"}',
        '{"summary":"private-provider-text","extra":1}',
        "[]",
        "not JSON",
    ],
)
def test_invalid_completion_never_exposes_provider_content(content):
    session = AgentSession(settings(), transport=httpx.MockTransport(lambda _: response(content)))
    try:
        with pytest.raises(ModelCallError) as error:
            session.json("data", "JSON", {}, DataSummary, max_output_tokens=192)
        assert "private-provider-text" not in str(error.value)
        assert session.events[-1].status == "failed"
        assert content not in session.events[-1].summary
    finally:
        session.close()


@pytest.mark.parametrize("value", [float("nan"), float("inf"), 10**400, True])
def test_fact_schema_failures_are_static_even_on_numeric_overflow(value):
    text = json.dumps(
        {
            "section_id": "s1",
            "metric_id": "project_count",
            "value": value,
            "unit": "count",
            "source_ids": ["projects.csv"],
        }
    )
    with pytest.raises(ModelCallError, match="JSON validation"):
        parse_json_model(FactClaim, text)


@pytest.mark.parametrize("finish", ["length", "content_filter", []])
def test_truncated_or_malformed_completion_is_rejected(finish):
    with pytest.raises(ModelCallError):
        response_message({"choices": [{"message": {"content": "x"}, "finish_reason": finish}]})


def test_service_failure_is_not_retried_and_missing_usage_is_not_zero():
    session = AgentSession(settings(), transport=httpx.MockTransport(lambda _: httpx.Response(503)))
    try:
        with pytest.raises(ModelCallError):
            session.chat("manager", [], max_output_tokens=256)
        assert session.request_count == 1
        assert session.usage_statistics["total_tokens"] is None
        assert session.events[-1].status == "failed"
    finally:
        session.close()


@pytest.mark.parametrize(
    "options",
    [
        {"max_requests": 13},
        {"max_requests": True},
        {"max_total_output_tokens": 5569},
        {"mode": "offline_mock"},
    ],
)
def test_invalid_session_budget_or_unbound_mock_is_rejected(options):
    with pytest.raises(ConfigurationError):
        AgentSession(settings(), **options)


def test_provider_usage_aggregates_without_storing_reasoning_or_raw_response():
    def handler(_):
        reply = response('{"summary":"ok"}')
        payload = json.loads(reply.content)
        payload["usage"] = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        payload["choices"][0]["message"]["reasoning_content"] = "PRIVATE_REASONING"
        return httpx.Response(200, json=payload)

    session = AgentSession(settings(), transport=httpx.MockTransport(handler))
    try:
        session.json("data", "JSON", {}, DataSummary, max_output_tokens=192)
        session.json("data", "JSON", {}, DataSummary, max_output_tokens=192)
        assert session.usage_statistics["total_tokens"] == 30
        assert "PRIVATE_REASONING" not in json.dumps(
            [event.model_dump() for event in session.events]
        )
    finally:
        session.close()


def test_context_limit_and_option_override_fail_before_spending_requests():
    session = AgentSession(settings(), transport=httpx.MockTransport(lambda _: response("OK")))
    try:
        with pytest.raises(ModelCallError, match="size limit"):
            session.chat("data", [{"role": "user", "content": "x" * 16001}], max_output_tokens=128)
        with pytest.raises(ModelCallError, match="override"):
            session.chat("data", [], max_output_tokens=128, thinking={"type": "enabled"})
        assert session.request_count == 0
        assert session.reserved_output_tokens == 0
    finally:
        session.close()
