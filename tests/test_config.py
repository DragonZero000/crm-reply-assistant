import pytest
from pydantic import ValidationError

from app.config import Settings


def test_defaults(monkeypatch):
    for name in ("LLM_MODEL", "LLM_BASE_URL", "LLM_API_KEY", "HISTORY_LIMIT"):
        monkeypatch.delenv(name, raising=False)
    s = Settings(_env_file=None)
    assert s.llm_base_url == "http://127.0.0.1:1234/v1"
    assert s.llm_model == "ornith-1.0-35b-mtp-apex"
    assert s.history_limit == 10
    assert s.kb_path.name == "knowledge_base.json"


def test_env_override(monkeypatch):
    monkeypatch.setenv("HISTORY_LIMIT", "4")
    monkeypatch.setenv("LLM_MODEL", "other-model")
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    s = Settings(_env_file=None)
    assert s.history_limit == 4
    assert s.llm_model == "other-model"
    assert s.llm_api_key.get_secret_value() == "sk-test"


def test_base_url_gets_v1_prefix():
    assert Settings(_env_file=None, llm_base_url="http://127.0.0.1:1234").llm_base_url == "http://127.0.0.1:1234/v1"
    assert Settings(_env_file=None, llm_base_url="http://127.0.0.1:1234/").llm_base_url == "http://127.0.0.1:1234/v1"
    assert Settings(_env_file=None, llm_base_url="https://api.openai.com/v1").llm_base_url == "https://api.openai.com/v1"


def test_crm_defaults():
    s = Settings(_env_file=None)
    assert s.crm_mode == "mock"
    assert s.webhook_secret is None
    assert s.amo_subdomain is None and s.amo_access_token is None


def test_amo_mode_with_all_settings():
    s = Settings(
        _env_file=None, crm_mode="amo", amo_subdomain="demo", amo_access_token="tkn", webhook_secret="s3cret"
    )
    assert s.amo_access_token.get_secret_value() == "tkn"


@pytest.mark.parametrize("missing", ["amo_subdomain", "amo_access_token", "webhook_secret"])
def test_amo_mode_requires_setting(missing):
    values = {"amo_subdomain": "demo", "amo_access_token": "tkn", "webhook_secret": "s3cret"}
    values[missing] = ""
    with pytest.raises(ValidationError, match=missing.upper()):
        Settings(_env_file=None, crm_mode="amo", **values)


def test_llm_reliability_defaults(monkeypatch):
    for name in ("LLM_TIMEOUT_SECONDS", "LLM_MAX_RETRIES", "LLM_PRICE_INPUT_PER_1M", "LLM_PRICE_OUTPUT_PER_1M"):
        monkeypatch.delenv(name, raising=False)
    s = Settings(_env_file=None)
    assert s.llm_timeout_seconds == 300
    assert s.llm_max_retries == 0
    assert s.llm_price_input_per_1m is None and s.llm_price_output_per_1m is None


def test_empty_price_is_unset(monkeypatch):
    monkeypatch.setenv("LLM_PRICE_INPUT_PER_1M", "")
    monkeypatch.setenv("LLM_PRICE_OUTPUT_PER_1M", "4.0")
    s = Settings(_env_file=None)
    assert s.llm_price_input_per_1m is None
    assert s.llm_price_output_per_1m == 4.0


@pytest.mark.parametrize("field", ["llm_price_input_per_1m", "llm_price_output_per_1m", "llm_max_retries"])
def test_negative_values_rejected(field):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: -1})
