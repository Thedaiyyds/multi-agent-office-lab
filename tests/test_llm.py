"""Offline HTTP mocks validate adapter behavior, not live model compatibility."""

import json

import httpx
import pytest

from office_agents.config import Settings
from office_agents.llm import ModelCallError, OpenAICompatibleClient


def settings(**overrides):
    values = {
        "base_url": "https://model.invalid/v1",
        "model": "test-model",
        "api_key": "secret-test-key",
        "timeout_seconds": 1,
        "max_retries": 2,
    }
    values.update(overrides)
    return Settings(**values)


def test_chat_sends_configured_request_and_preserves_response():
    requests = []
    payload = {"choices": [{"message": {"content": "hello"}}]}

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=payload)

    client = OpenAICompatibleClient(settings(), transport=httpx.MockTransport(respond))
    try:
        result = client.chat([{"role": "user", "content": "test"}], temperature=0)
    finally:
        client.close()

    assert result == payload
    assert len(requests) == 1
    assert str(requests[0].url) == "https://model.invalid/v1/chat/completions"
    assert requests[0].headers["Authorization"] == "Bearer secret-test-key"
    assert json.loads(requests[0].content) == {
        "model": "test-model",
        "messages": [{"role": "user", "content": "test"}],
        "temperature": 0,
    }


def test_local_service_without_key_omits_authorization_header():
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    client = OpenAICompatibleClient(settings(api_key=""), transport=httpx.MockTransport(respond))
    try:
        client.chat([{"role": "user", "content": "test"}])
    finally:
        client.close()
    assert len(requests) == 1
    assert "Authorization" not in requests[0].headers


@pytest.mark.parametrize("status", [429, 500, 503])
def test_transient_failure_retries_are_bounded_and_safe(status):
    calls = []
    sleeps = []

    def respond(request):
        calls.append(request)
        return httpx.Response(status, text="secret-test-key upstream diagnostics")

    client = OpenAICompatibleClient(
        settings(), transport=httpx.MockTransport(respond), sleep=sleeps.append
    )
    try:
        with pytest.raises(ModelCallError) as error:
            client.chat([{"role": "user", "content": "test"}])
    finally:
        client.close()

    assert len(calls) == 3  # First attempt plus max_retries=2.
    assert len(sleeps) == 2
    assert "secret-test-key" not in str(error.value)
    assert "upstream diagnostics" not in str(error.value)


@pytest.mark.parametrize("status", [400, 401, 403])
def test_invalid_request_and_authentication_are_not_retried(status):
    calls = []
    sleeps = []

    def respond(request):
        calls.append(request)
        return httpx.Response(status, text="secret-test-key")

    client = OpenAICompatibleClient(
        settings(), transport=httpx.MockTransport(respond), sleep=sleeps.append
    )
    try:
        with pytest.raises(ModelCallError) as error:
            client.chat([{"role": "user", "content": "test"}])
    finally:
        client.close()

    assert len(calls) == 1
    assert sleeps == []
    assert "secret-test-key" not in str(error.value)


def test_network_timeout_retries_without_leaking_exception_details():
    calls = []

    def respond(request):
        calls.append(request)
        raise httpx.ReadTimeout("secret-test-key in provider error", request=request)

    client = OpenAICompatibleClient(
        settings(max_retries=1),
        transport=httpx.MockTransport(respond),
        sleep=lambda _: None,
    )
    try:
        with pytest.raises(ModelCallError) as error:
            client.chat([{"role": "user", "content": "test"}])
    finally:
        client.close()

    assert len(calls) == 2
    assert "secret-test-key" not in str(error.value)


def test_transient_failure_can_recover():
    calls = []

    def respond(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    client = OpenAICompatibleClient(
        settings(), transport=httpx.MockTransport(respond), sleep=lambda _: None
    )
    try:
        result = client.chat([{"role": "user", "content": "test"}])
    finally:
        client.close()

    assert len(calls) == 2
    assert result["choices"][0]["message"]["content"] == "ok"
