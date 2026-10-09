"""Environment configuration without exposing credentials in diagnostics."""

import math
import os
from urllib.parse import urlsplit

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field


class ConfigurationError(ValueError):
    """A configuration problem with a safe, static message."""


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str = ""
    model: str = ""
    api_key: str = Field(default="", repr=False)
    timeout_seconds: float = 30.0
    max_retries: int = 2

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(override=False)
        try:
            timeout = float(os.getenv("LLM_TIMEOUT_SECONDS", "30"))
            retries = int(os.getenv("LLM_MAX_RETRIES", "2"))
        except ValueError:
            raise ConfigurationError("Timeout and retry settings must be numeric.") from None
        settings = cls(
            base_url=os.getenv("LLM_BASE_URL", "").strip(),
            model=os.getenv("LLM_MODEL", "").strip(),
            api_key=os.getenv("LLM_API_KEY", "").strip(),
            timeout_seconds=timeout,
            max_retries=retries,
        )
        settings._validate_limits()
        return settings

    def _validate_limits(self) -> None:
        if not math.isfinite(self.timeout_seconds) or not 0 < self.timeout_seconds <= 300:
            raise ConfigurationError("LLM_TIMEOUT_SECONDS must be greater than 0 and at most 300.")
        if isinstance(self.max_retries, bool) or not 0 <= self.max_retries <= 5:
            raise ConfigurationError("LLM_MAX_RETRIES must be an integer from 0 to 5.")

    def validate_for_live(self) -> None:
        self._validate_limits()
        if not self.base_url:
            raise ConfigurationError("Set LLM_BASE_URL before calling a model.")
        if not self.model:
            raise ConfigurationError("Set LLM_MODEL before calling a model.")
        try:
            url = urlsplit(self.base_url)
            valid = (
                url.scheme in {"http", "https"}
                and bool(url.hostname)
                and url.username is None
                and url.password is None
                and not url.query
                and not url.fragment
            )
            _ = url.port
        except ValueError:
            valid = False
        if not valid:
            raise ConfigurationError(
                "LLM_BASE_URL must be an HTTP(S) API base URL "
                "without credentials, query or fragment."
            )

    @property
    def chat_url(self) -> str:
        self.validate_for_live()
        return self.base_url.rstrip("/") + "/chat/completions"
