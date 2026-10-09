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

    def chat(self, messages: list[dict[str, Any]], **options: Any) -> dict[str, Any]:
        payload = {"model": self.settings.model, "messages": messages, **options}
        for attempt in range(self.settings.max_retries + 1):
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
                    return data
            if attempt < self.settings.max_retries:
                self._sleep(min(2**attempt, 4))
        raise ModelCallError(error) from None
