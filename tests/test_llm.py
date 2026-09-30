from types import SimpleNamespace

import httpx
import openai
import pytest
from pydantic import ValidationError

from app.config import Settings
from app.llm import CallContext, LLMFailure, OpenAILLMClient, estimate_cost
from app.prompt import build_system_prompt
from tests.fakes import llm_output


def test_unknown_kb_id_rejected(output_model):
    with pytest.raises(ValidationError):
        output_model.model_validate(llm_output(used_kb_ids=["faq_unknown"]))


def test_unknown_product_rejected(output_model):
    upsell = [{"product_id": "unknown", "why_now": "..."}]
    with pytest.raises(ValidationError):
        output_model.model_validate(llm_output(upsell=upsell))


def test_needs_human_without_reason_becomes_other(output_model):
    out = output_model.model_validate(llm_output(needs_human=True, reason=None))
    assert (out.needs_human, out.reason) == (True, "other")


def test_reason_without_needs_human_sets_needs_human(output_model):
    out = output_model.model_validate(llm_output(needs_human=False, reason="complaint"))
    assert (out.needs_human, out.reason) == (True, "complaint")


def test_schema_is_structured_output_compatible(output_model):
    schema = output_model.model_json_schema()
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {
        "client_reply", "needs_human", "reason", "manager_note", "used_kb_ids", "upsell"
    }


def test_system_prompt(kb):
    prompt = build_system_prompt(kb)
    assert prompt.endswith("</knowledge_base>")
    assert 'id="faq_delivery"' in prompt
    assert "2026-09-30" not in prompt.replace(kb.version, "")  # в промпте нет даты, кроме версии базы
    assert prompt == build_system_prompt(kb)


# --- OpenAILLMClient: разбор ответа SDK без сети ---

def make_client(monkeypatch, result=None, error=None, **settings):
    client = OpenAILLMClient(
        Settings(_env_file=None, llm_base_url="http://127.0.0.1:1234/v1", **settings)
    )
    captured = {}

    def fake_parse(**kwargs):
        captured.update(kwargs)
        if error:
            raise error
        return result

    monkeypatch.setattr(client._client.chat.completions, "parse", fake_parse)
    return client, captured


def fake_completion(parsed=None, refusal=None, choices=True, usage=(10, 5)):
    message = SimpleNamespace(parsed=parsed, refusal=refusal)
    if usage is not None:
        usage = SimpleNamespace(prompt_tokens=usage[0], completion_tokens=usage[1])
    return SimpleNamespace(
        id="c1", model="m", usage=usage,
        choices=[SimpleNamespace(message=message, finish_reason="stop")] if choices else [],
    )


def test_request_shape(monkeypatch, output_model):
    parsed = output_model.model_validate(llm_output())
    client, captured = make_client(monkeypatch, result=fake_completion(parsed))

    assert client.generate("SYS", "USER", output_model) is parsed
    assert str(client._client.base_url).startswith("http://127.0.0.1:1234/v1")
    assert captured["model"] == "ornith-1.0-35b-mtp-apex"
    assert captured["response_format"] is output_model
    assert captured["messages"] == [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "USER"},
    ]


@pytest.mark.parametrize(
    "completion, kind",
    [
        (fake_completion(refusal="I can't help"), "refusal"),
        (fake_completion(parsed=None), "invalid_output"),
        (fake_completion(choices=False), "invalid_output"),
    ],
)
def test_bad_completion(monkeypatch, output_model, completion, kind):
    client, _ = make_client(monkeypatch, result=completion)
    with pytest.raises(LLMFailure) as exc:
        client.generate("SYS", "USER", output_model)
    assert exc.value.kind == kind


def _length_error():
    return openai.LengthFinishReasonError(completion=SimpleNamespace(usage=None))


@pytest.mark.parametrize(
    "error, kind",
    [
        (openai.APIConnectionError(request=httpx.Request("POST", "http://127.0.0.1:1234")), "api_error"),
        (openai.APITimeoutError(request=httpx.Request("POST", "http://127.0.0.1:1234")), "timeout"),
        (openai.ContentFilterFinishReasonError(), "refusal"),
        (ValueError("bad json"), "invalid_output"),
        (TypeError("unexpected"), "client_error"),
    ],
)
def test_sdk_errors(monkeypatch, output_model, error, kind):
    client, _ = make_client(monkeypatch, error=error)
    with pytest.raises(LLMFailure) as exc:
        client.generate("SYS", "USER", output_model)
    assert exc.value.kind == kind


def test_length_error(monkeypatch, output_model):
    try:
        error = _length_error()
    except Exception:
        pytest.skip("конструктор LengthFinishReasonError изменился")
    client, _ = make_client(monkeypatch, error=error)
    with pytest.raises(LLMFailure) as exc:
        client.generate("SYS", "USER", output_model)
    assert exc.value.kind == "max_tokens"


def test_no_retries_by_default():
    client = OpenAILLMClient(Settings(_env_file=None))
    assert client._client.max_retries == 0
    assert client._client.timeout == 300


def test_retries_from_settings():
    assert OpenAILLMClient(Settings(_env_file=None, llm_max_retries=2))._client.max_retries == 2


# --- Оценка стоимости и лог вызова ---

def test_estimate_cost():
    assert estimate_cost(3000, 500, 1.0, 4.0) == pytest.approx(0.005)
    assert estimate_cost(3000, 500, 1.0, None) is None
    assert estimate_cost(3000, 500, None, None) is None
    assert estimate_cost(None, 500, 1.0, 4.0) is None


def call_lines(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.getMessage().startswith("llm_call ")]


def call_fields(caplog) -> dict[str, str]:
    [line] = call_lines(caplog)  # ровно одна строка на вызов
    return dict(part.split("=", 1) for part in line.split()[1:])


def test_log_success(monkeypatch, caplog, output_model):
    caplog.set_level("INFO", logger="app.llm")
    parsed = output_model.model_validate(llm_output())
    client, _ = make_client(monkeypatch, result=fake_completion(parsed, usage=(3100, 280)))
    client.generate("SYS", "USER", output_model)
    fields = call_fields(caplog)
    assert fields["outcome"] == "ok"
    assert (fields["prompt_tokens"], fields["completion_tokens"]) == ("3100", "280")
    assert fields["cost"] == "n/a"
    assert (fields["lead_id"], fields["message_id"]) == ("-", "-")
    assert fields["model"] == "m"
    assert int(fields["latency_ms"]) >= 0


def test_log_cost_and_context(monkeypatch, caplog, output_model):
    caplog.set_level("INFO", logger="app.llm")
    parsed = output_model.model_validate(llm_output())
    client, _ = make_client(
        monkeypatch,
        result=fake_completion(parsed, usage=(3000, 500)),
        llm_price_input_per_1m=1.0,
        llm_price_output_per_1m=4.0,
    )
    client.generate("SYS", "USER", output_model, CallContext(lead_id=555, message_id="msg-1"))
    fields = call_fields(caplog)
    assert fields["cost"] == "0.005000"
    assert (fields["lead_id"], fields["message_id"]) == ("555", "msg-1")


def test_log_no_kb_answer_is_ok(monkeypatch, caplog, output_model):
    caplog.set_level("INFO", logger="app.llm")
    parsed = output_model.model_validate(
        llm_output(needs_human=True, reason="no_kb_answer", used_kb_ids=[])
    )
    client, _ = make_client(monkeypatch, result=fake_completion(parsed))
    client.generate("SYS", "USER", output_model)
    assert call_fields(caplog)["outcome"] == "ok"


@pytest.mark.parametrize("reply", ["", "   "])
def test_empty_client_reply_is_invalid_output(monkeypatch, output_model, reply):
    parsed = output_model.model_validate(llm_output(client_reply=reply))
    client, _ = make_client(monkeypatch, result=fake_completion(parsed))
    with pytest.raises(LLMFailure) as exc_info:
        client.generate("SYS", "USER", output_model)
    assert exc_info.value.kind == "invalid_output"


def test_log_empty_client_reply(monkeypatch, caplog, output_model):
    caplog.set_level("INFO", logger="app.llm")
    parsed = output_model.model_validate(llm_output(client_reply=""))
    client, _ = make_client(monkeypatch, result=fake_completion(parsed))
    with pytest.raises(LLMFailure):
        client.generate("SYS", "USER", output_model)
    assert call_fields(caplog)["outcome"] == "invalid_output"


def test_log_without_usage(monkeypatch, caplog, output_model):
    caplog.set_level("INFO", logger="app.llm")
    parsed = output_model.model_validate(llm_output())
    client, _ = make_client(
        monkeypatch,
        result=fake_completion(parsed, usage=None),
        llm_price_input_per_1m=1.0,
        llm_price_output_per_1m=4.0,
    )
    assert client.generate("SYS", "USER", output_model) is parsed
    fields = call_fields(caplog)
    assert (fields["prompt_tokens"], fields["completion_tokens"], fields["cost"]) == ("n/a", "n/a", "n/a")


@pytest.mark.parametrize(
    "error, kind",
    [
        (openai.APITimeoutError(request=httpx.Request("POST", "http://127.0.0.1:1234")), "timeout"),
        (TypeError("unexpected"), "client_error"),
    ],
)
def test_log_failure(monkeypatch, caplog, output_model, error, kind):
    caplog.set_level("INFO", logger="app.llm")
    client, _ = make_client(monkeypatch, error=error)
    with pytest.raises(LLMFailure):
        client.generate("SYS", "USER", output_model)
    fields = call_fields(caplog)
    assert fields["outcome"] == kind
    assert (fields["prompt_tokens"], fields["completion_tokens"], fields["cost"]) == ("n/a", "n/a", "n/a")
    assert int(fields["latency_ms"]) >= 0


def test_log_refusal_keeps_usage(monkeypatch, caplog, output_model):
    caplog.set_level("INFO", logger="app.llm")
    client, _ = make_client(monkeypatch, result=fake_completion(refusal="no"))
    with pytest.raises(LLMFailure):
        client.generate("SYS", "USER", output_model)
    fields = call_fields(caplog)
    assert fields["outcome"] == "refusal"
    assert fields["prompt_tokens"] == "10"  # токены потрачены и при отказе


def test_log_max_tokens_keeps_usage(monkeypatch, caplog, output_model):
    caplog.set_level("INFO", logger="app.llm")
    usage = SimpleNamespace(prompt_tokens=3000, completion_tokens=8000)
    try:
        error = openai.LengthFinishReasonError(completion=SimpleNamespace(usage=usage))
    except Exception:
        pytest.skip("конструктор LengthFinishReasonError изменился")
    client, _ = make_client(monkeypatch, error=error)
    with pytest.raises(LLMFailure):
        client.generate("SYS", "USER", output_model)
    fields = call_fields(caplog)
    assert (fields["outcome"], fields["completion_tokens"]) == ("max_tokens", "8000")


def test_log_has_no_message_text_or_key(monkeypatch, caplog, output_model):
    caplog.set_level("INFO", logger="app.llm")
    parsed = output_model.model_validate(llm_output())
    client, _ = make_client(monkeypatch, result=fake_completion(parsed), llm_api_key="sk-secret-123")
    client.generate("SYS PROMPT", "Клиент: хочу витамин D", output_model)
    [line] = call_lines(caplog)
    assert "витамин" not in line and "SYS PROMPT" not in line and "sk-secret-123" not in line
