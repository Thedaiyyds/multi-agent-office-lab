"""Bounded shared model session for independent role agents."""

import json
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

import httpx
from pydantic import BaseModel, Field, ValidationError

from office_agents.agent_schemas import AgentEvent, Role, RoleRun
from office_agents.config import ConfigurationError, Settings
from office_agents.llm import ModelCallError, OpenAICompatibleClient
from office_agents.schemas import ContractModel

ROLE_OUTPUT_CAPS = {"manager": 256, "planner": 384, "data": 192, "writer": 768, "checker": 256}


def response_message(response: dict[str, Any]) -> dict[str, Any]:
    try:
        choice = response["choices"][0]
        message = choice["message"]
    except (KeyError, IndexError, TypeError):
        raise ModelCallError("Agent response has no valid completion message.") from None
    if not isinstance(choice, dict) or not isinstance(message, dict):
        raise ModelCallError("Agent response has no valid completion message.")
    finish_reason = choice.get("finish_reason")
    if finish_reason is not None and not isinstance(finish_reason, str):
        raise ModelCallError("Agent response has an invalid completion status.")
    if finish_reason in {"length", "content_filter"}:
        raise ModelCallError("Agent response was truncated or blocked.")
    return message


def response_content(response: dict[str, Any]) -> str:
    content = response_message(response).get("content")
    if not isinstance(content, str) or not content.strip() or len(content) > 12000:
        raise ModelCallError("Agent response has invalid text content.")
    return content


def _json_default(value):
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    raise TypeError("Unsupported context value.")


def parse_json_model(output_model: type[BaseModel], content: str):
    """Reject ambiguous JSON and validate without exposing provider text."""

    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key.")
            result[key] = value
        return result

    def reject_constant(value):
        raise ValueError("Nonfinite JSON value.")

    try:
        value = json.loads(content, object_pairs_hook=unique_pairs, parse_constant=reject_constant)
        if not isinstance(value, dict):
            raise ValueError("JSON object required.")
        return output_model.model_validate(value)
    except (ValidationError, ValueError, OverflowError, TypeError):
        raise ModelCallError("Agent output failed local JSON validation.") from None


class AgentSession:
    def __init__(
        self,
        settings: Settings,
        *,
        profile: Literal["generic", "deepseek"] = "deepseek",
        mode: Literal["live", "offline_mock"] = "live",
        max_requests: int = 7,
        max_total_output_tokens: int = 2240,
        transport: httpx.BaseTransport | None = None,
    ):
        if profile not in {"generic", "deepseek"} or mode not in {"live", "offline_mock"}:
            raise ConfigurationError("Unsupported agent session configuration.")
        if type(max_requests) is not int or not 1 <= max_requests <= 7:
            raise ConfigurationError("Agent request budget must be an integer from 1 to 7.")
        if type(max_total_output_tokens) is not int or not 1 <= max_total_output_tokens <= 2240:
            raise ConfigurationError("Agent output budget must be an integer from 1 to 2240.")
        if mode == "offline_mock" and not isinstance(transport, httpx.MockTransport):
            raise ConfigurationError("Mock mode requires an explicit local MockTransport.")
        self.mode = mode
        self.profile = profile
        self.max_requests = max_requests
        self.max_total_output_tokens = max_total_output_tokens
        self.reserved_output_tokens = 0
        self.events: list[AgentEvent] = []
        self.client = OpenAICompatibleClient(
            settings.model_copy(update={"max_retries": 0}), transport=transport
        )

    @property
    def request_count(self):
        return self.client.request_count

    @property
    def usage_statistics(self):
        return self.client.usage_statistics

    def close(self):
        self.client.close()

    def chat(
        self, role: Role, messages: list[dict[str, Any]], *, max_output_tokens: int, **options
    ):
        cap = ROLE_OUTPUT_CAPS.get(role)
        if cap is None or type(max_output_tokens) is not int or not 1 <= max_output_tokens <= cap:
            raise ModelCallError("Agent output limit is invalid.")
        if self.client.settings.max_retries != 0:
            raise ModelCallError("Agent requests require zero retries.")
        if self.request_count >= self.max_requests:
            raise ModelCallError("Agent request budget exhausted.")
        if self.reserved_output_tokens + max_output_tokens > self.max_total_output_tokens:
            raise ModelCallError("Agent output budget exhausted.")
        if {"max_tokens", "model", "thinking", "temperature"} & options.keys():
            raise ModelCallError("Agent options cannot override the shared limits.")
        copied = [dict(message) for message in messages]
        prefix = f"ROLE={role}\n"
        if copied and copied[0].get("role") == "system":
            copied[0]["content"] = prefix + str(copied[0].get("content", ""))
        else:
            copied.insert(0, {"role": "system", "content": prefix})
        try:
            serialized = json.dumps(copied, ensure_ascii=False, default=_json_default)
        except (TypeError, ValueError):
            raise ModelCallError("Agent context cannot be serialized.") from None
        if len(serialized) > 16000:
            raise ModelCallError("Agent context exceeds the local size limit.")
        self.reserved_output_tokens += max_output_tokens
        settings = {"max_tokens": max_output_tokens, "temperature": 0}
        if self.profile == "deepseek":
            settings["thinking"] = {"type": "disabled"}
        try:
            response = self.client.chat(copied, **settings, **options)
            response_message(response)
        except ModelCallError:
            self.events.append(
                AgentEvent(
                    role=role,
                    event_type="model_request",
                    status="failed",
                    created_at=datetime.now(UTC).isoformat(),
                    summary="Model request or completion shape failed; no raw response stored.",
                )
            )
            raise
        self.events.append(
            AgentEvent(
                role=role,
                event_type="model_request",
                status="passed",
                created_at=datetime.now(UTC).isoformat(),
                summary="Received completion; role output requires local validation.",
            )
        )
        return response

    def json(
        self,
        role: Role,
        system: str,
        user: Any,
        output_model: type[BaseModel],
        *,
        max_output_tokens,
    ):
        try:
            context = (
                user
                if isinstance(user, str)
                else json.dumps(user, ensure_ascii=False, default=_json_default)
            )
        except (TypeError, ValueError):
            raise ModelCallError("Agent context cannot be serialized.") from None
        response = self.chat(
            role,
            [{"role": "system", "content": system}, {"role": "user", "content": context}],
            max_output_tokens=max_output_tokens,
            response_format={"type": "json_object"},
        )
        try:
            return parse_json_model(output_model, response_content(response))
        except ModelCallError:
            self.events[-1].status = "failed"
            self.events[
                -1
            ].summary = "Completion failed local JSON validation; raw text not stored."
            raise ModelCallError("Agent output failed local JSON validation.") from None

    def record_tool(self, role, tool_name, arguments, status, summary):
        self.events.append(
            AgentEvent(
                role=role,
                event_type="tool_execution",
                status=status,
                created_at=datetime.now(UTC).isoformat(),
                tool_name=tool_name,
                arguments=arguments,
                summary=summary,
            )
        )


class AgentRunReport(ContractModel):
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    mode: Literal["live", "offline_mock"]
    description: str = "Independent fixed role examples; not an orchestrated business workflow."
    status: Literal["passed", "needs_input", "review_failed", "failed"]
    runs: list[RoleRun]
    events: list[AgentEvent]
    request_count: int
    reserved_output_tokens: int
    usage: dict[str, int | None]
