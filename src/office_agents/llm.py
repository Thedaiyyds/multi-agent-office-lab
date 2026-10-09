"""Small OpenAI-compatible Chat Completions adapter with bounded retries."""

import time
from collections.abc import Callable
from typing import Any

import httpx

from office_agents.config import Settings


class ModelCallError(RuntimeError):
    """Safe error: never contains response bodies, URLs, credentials or provider text."""


class OpenAICompatibleClient:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        settings.validate_for_live()
        self.settings = settings
        self.request_count = 0
        self._usage_records: list[dict[str, int] | None] = []
        self._sleep = sleep
        headers = {"Content-Type": "application/json"}
        if settings.api_key:
            headers["Authorization"] = "Bearer " + settings.api_key
        self._client = httpx.Client(
            headers=headers,
            timeout=settings.timeout_seconds,
            transport=transport,
            follow_redirects=False,
        )

    def close(self) -> None:
        self._client.close()

    @property
    def usage_statistics(self) -> dict[str, int | None]:
        """Sum a field only when every HTTP attempt has its valid provider value.

        Missing/invalid usage or unsuccessful attempts produce None, never an
        invented zero. Reasoning tokens are a subset of completion tokens.
        """
        totals: dict[str, int | None] = {}
        for key in ("prompt_tokens", "completion_tokens", "total_tokens", "reasoning_tokens"):
            values = [record[key] for record in self._usage_records if record and key in record]
            totals[key] = (
                sum(values) if self.request_count and len(values) == self.request_count else None
            )
        return totals

    def _record_usage(self, data: dict[str, Any]) -> None:
        usage = data.get("usage")
        if not isinstance(usage, dict):
            return
        safe: dict[str, int] = {}
        for key in ("prompt_tokens", "completion_tokens", "total_tokens", "reasoning_tokens"):
            value = usage.get(key)
            if key == "reasoning_tokens" and value is None:
                details = usage.get("completion_tokens_details")
                if isinstance(details, dict):
                    value = details.get(key)
            if type(value) is int and value >= 0:
                safe[key] = value
        self._usage_records[-1] = safe

    def chat(self, messages: list[dict[str, Any]], **options: Any) -> dict[str, Any]:
        payload = {"model": self.settings.model, "messages": messages, **options}
        for attempt in range(self.settings.max_retries + 1):
            self.request_count += 1
            self._usage_records.append(None)
            try:
                response = self._client.post(self.settings.chat_url, json=payload)
            except httpx.TimeoutException:
                error = "Model request timed out."
            except httpx.RequestError:
                error = "Model connection failed."
            else:
                if response.status_code == 429 or 500 <= response.status_code < 600:
                    error = (
                        f"HTTP {response.status_code}: model service was temporarily unavailable "
                        "or rate limited."
                    )
                elif not 200 <= response.status_code < 300:
                    hints = {
                        400: "request parameters may be unsupported by this model service.",
                        401: "authentication failed; check the configured API key.",
                        403: "access denied; check model permissions.",
                        404: "endpoint or model not found; check API base path and model name.",
                    }
                    hint = hints.get(response.status_code, "model service rejected the request.")
                    raise ModelCallError(f"HTTP {response.status_code}: {hint}")
                else:
                    try:
                        data = response.json()
                    except ValueError:
                        raise ModelCallError("Model service returned invalid JSON.") from None
                    if not isinstance(data, dict):
                        raise ModelCallError("Model service returned an invalid response shape.")
                    self._record_usage(data)
                    return data
            if attempt < self.settings.max_retries:
                self._sleep(min(2**attempt, 4))
        raise ModelCallError(error) from None
