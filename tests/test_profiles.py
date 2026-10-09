"""Budget/profile and usage tests are offline HTTP mocks, never live evidence."""

import json

import httpx
import pytest

from office_agents.config import Settings
from office_agents.llm import OpenAICompatibleClient
from office_agents.probes import run_live_smoke, save_report


def run_mock_profile(*, profile="deepseek", failure=None, usages=None):
    requests = []
    sleeps = []

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        index = len(requests) - 1
        if failure is not None and index == failure[0]:
            if failure[1] == "timeout":
                raise httpx.ReadTimeout("secret-test-key provider exception", request=request)
            if isinstance(failure[1], int):
                return httpx.Response(failure[1], text="secret-test-key provider error")
        if "response_format" in body:
            content = (
                '{"number":8,"label":"probe"}'
                if failure is not None and index == failure[0] and failure[1] == "bad_json"
                else '{"number":7,"label":"probe"}'
            )
            message = {"content": content}
        elif body.get("tool_choice") == "none":
            message = {"content": "secret-provider-output 7"}
        elif "tools" in body:
            message = {
                "content": None,
                "tool_calls": [
                    {
                        "id": "offline-test-call",
                        "type": "function",
                        "function": {"name": "echo_number", "arguments": '{"number":7}'},
                    }
                ],
            }
        else:
            message = {"content": "secret-provider-output greeting"}
        data = {"choices": [{"message": {**message, "reasoning_content": "secret-reasoning"}}]}
        if usages is not None:
            usage = usages[index] if index < len(usages) else None
            if usage is not None:
                data["usage"] = usage
        return httpx.Response(200, json=data)

    def factory(settings):
        return OpenAICompatibleClient(
            settings, transport=httpx.MockTransport(respond), sleep=sleeps.append
        )

    report = run_live_smoke(
        Settings(
            base_url="https://model.invalid/v1",
            model="deepseek-offline-test",
            api_key="secret-test-key",
            max_retries=3,
        ),
        profile=profile,
        client_factory=factory,
    )
    return report, requests, sleeps


def test_deepseek_profile_caps_each_request_and_uses_supported_parameters():
    report, requests, sleeps = run_mock_profile()
    assert report.status == "passed"
    assert report.profile == "deepseek"
    assert report.max_output_tokens == 64
    assert report.request_count == len(requests) == 4
    assert sleeps == []
    for request in requests:
        assert request["max_tokens"] == 64
        assert request["thinking"] == {"type": "disabled"}
        assert request["temperature"] == 0
        assert "parallel_tool_calls" not in request
    assert requests[1]["response_format"] == {"type": "json_object"}
    assert requests[-1]["messages"][-1]["role"] == "tool"


@pytest.mark.parametrize("failure", [(0, 503), (0, 429), (0, "timeout"), (1, "bad_json")])
def test_deepseek_stops_on_first_failure_without_retries(failure):
    report, requests, sleeps = run_mock_profile(failure=failure)
    assert report.status == "failed"
    assert report.request_count == len(requests) == failure[0] + 1
    assert len(report.probes) == failure[0] + 1
    assert report.probes[-1].passed is False
    assert sleeps == []
    assert "secret-test-key" not in report.model_dump_json()


def test_generic_profile_preserves_schema_and_continue_after_probe_failure():
    report, requests, _ = run_mock_profile(profile="generic", failure=(1, "bad_json"))
    assert report.status == "failed"
    assert [probe.passed for probe in report.probes] == [True, False, True]
    assert len(requests) == 4
    assert requests[1]["response_format"]["type"] == "json_schema"
    assert all(request["max_tokens"] == 64 for request in requests)


def usage(prompt, completion, reasoning=0):
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
        "completion_tokens_details": {"reasoning_tokens": reasoning},
        "untrusted_provider_field": "secret-provider-output",
    }


def test_usage_sums_numeric_fields_from_all_four_requests_without_saving_text(tmp_path):
    report, _, _ = run_mock_profile(
        usages=[usage(10, 2, 1), usage(20, 3, 1), usage(30, 4, 2), usage(40, 5, 0)]
    )
    assert report.usage == {
        "prompt_tokens": 100,
        "completion_tokens": 14,
        "total_tokens": 114,
        "reasoning_tokens": 4,
    }
    stored = save_report(report, tmp_path).read_text(encoding="utf-8")
    for secret in (
        "secret-test-key",
        "secret-provider-output",
        "secret-reasoning",
        "untrusted_provider_field",
    ):
        assert secret not in stored


def test_completely_missing_usage_is_unavailable_not_zero():
    report, _, _ = run_mock_profile()
    assert report.usage is not None
    assert all(value is None for value in report.usage.values())


def test_one_missing_response_usage_prevents_partial_sum_being_reported_as_total():
    report, _, _ = run_mock_profile(usages=[usage(10, 2), None, usage(30, 4), usage(40, 5)])
    assert report.usage is not None
    assert all(value is None for value in report.usage.values())


@pytest.mark.parametrize("invalid", [None, -1, True, "10", 10.5])
def test_invalid_usage_field_is_unavailable_while_valid_fields_still_sum(invalid):
    first = usage(10, 2)
    first["prompt_tokens"] = invalid
    report, _, _ = run_mock_profile(usages=[first, usage(20, 3), usage(30, 4), usage(40, 5)])
    assert report.usage["prompt_tokens"] is None
    assert report.usage["completion_tokens"] == 14
    assert report.usage["total_tokens"] == 114


def test_missing_reasoning_usage_is_unavailable_not_inferred_from_disabled_thinking():
    first = usage(10, 2)
    del first["completion_tokens_details"]
    report, _, _ = run_mock_profile(usages=[first, usage(20, 3), usage(30, 4), usage(40, 5)])
    assert report.usage["reasoning_tokens"] is None
    assert report.usage["prompt_tokens"] == 100


def test_failed_http_request_makes_total_usage_unavailable():
    report, requests, _ = run_mock_profile(failure=(1, 503), usages=[usage(10, 2)])
    assert report.status == "failed"
    assert len(requests) == 2
    assert all(value is None for value in report.usage.values())
