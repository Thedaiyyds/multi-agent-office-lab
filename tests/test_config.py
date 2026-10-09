"""Configuration checks do not contact a model provider."""

import pytest

from office_agents.config import ConfigurationError, Settings


@pytest.mark.parametrize("missing", ["base_url", "model"])
def test_live_requires_each_essential_setting(missing):
    values = {
        "base_url": "https://model.invalid/v1",
        "model": "test-model",
        "api_key": "secret-test-key",
    }
    values[missing] = ""
    with pytest.raises(ConfigurationError) as error:
        Settings(**values).validate_for_live()
    assert "secret-test-key" not in str(error.value)


def test_complete_configuration_is_accepted():
    Settings(
        base_url="https://model.invalid/v1", model="test-model", api_key="secret-test-key"
    ).validate_for_live()


def test_local_service_can_omit_key():
    Settings(base_url="http://127.0.0.1:11434/v1", model="local-model").validate_for_live()


@pytest.mark.parametrize(
    "base_url",
    [
        "file:///private/data",
        "https://user:secret-test-key@model.invalid/v1",
        "https://model.invalid/v1?key=secret-test-key",
        "https://model.invalid/v1#secret-test-key",
        "https://model.invalid:invalid/v1",
    ],
)
def test_unsafe_or_invalid_url_is_rejected_without_echoing_it(base_url):
    with pytest.raises(ConfigurationError) as error:
        Settings(base_url=base_url, model="test-model").validate_for_live()
    assert "secret-test-key" not in str(error.value)
    assert base_url not in str(error.value)


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("LLM_TIMEOUT_SECONDS", "secret-test-key"),
        ("LLM_TIMEOUT_SECONDS", "nan"),
        ("LLM_TIMEOUT_SECONDS", "0"),
        ("LLM_TIMEOUT_SECONDS", "301"),
        ("LLM_MAX_RETRIES", "secret-test-key"),
        ("LLM_MAX_RETRIES", "-1"),
        ("LLM_MAX_RETRIES", "6"),
    ],
)
def test_invalid_environment_limits_return_safe_configuration_error(monkeypatch, variable, value):
    monkeypatch.setattr("office_agents.config.load_dotenv", lambda **_: None)
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "30")
    monkeypatch.setenv("LLM_MAX_RETRIES", "2")
    monkeypatch.setenv(variable, value)
    with pytest.raises(ConfigurationError) as error:
        Settings.from_env()
    assert "secret-test-key" not in str(error.value)


def test_settings_repr_hides_key():
    assert "secret-test-key" not in repr(Settings(api_key="secret-test-key"))
