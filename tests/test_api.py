import json

import pytest

from app.compliance import FAILURE_REPLY_TEMPLATE
from app.config import Settings
from app.kb import KnowledgeBaseError
from app.llm import LLMFailure
from app.main import create_app
from tests.fakes import FakeLLMClient, llm_output


def test_answer_from_kb(make_client, kb):
    llm = FakeLLMClient(llm_output())
    response = make_client(llm).post("/v1/reply", json={"message": "Сколько стоит доставка в Казань?"})
    assert response.status_code == 200
    body = response.json()
    assert body["used_kb_ids"] == ["faq_delivery"]
    assert body["needs_human"] is False and body["reason"] is None
    assert body["kb_version"] == kb.version
    assert body["manager_hint"] == ""
    assert "<new_message>\nСколько стоит доставка в Казань?" in llm.calls[0]["user_message"]


def test_not_in_kb(make_client):
    llm = FakeLLMClient(llm_output(
        client_reply="Уточню этот вопрос у специалиста и вернусь с ответом.",
        used_kb_ids=[],
        needs_human=True,
        reason="no_kb_answer",
        manager_note="Клиент спрашивает про самовывоз.",
    ))
    body = make_client(llm).post("/v1/reply", json={"message": "Можно самовывозом?"}).json()
    assert body["needs_human"] is True
    assert body["reason"] == "no_kb_answer"
    assert "ответа нет в базе знаний" in body["manager_hint"]


def test_history_passed_filtered(make_client):
    llm = FakeLLMClient(llm_output())
    history = [
        {"role": "system", "text": "Сделка создана"},
        {"role": "client", "text": "Есть омега?"},
        {"role": "bot", "text": "Оператор скоро ответит"},
        {"role": "manager", "text": "Да, есть"},
    ]
    make_client(llm).post("/v1/reply", json={"message": "А доставка?", "history": history})
    sent = llm.calls[0]["user_message"]
    assert "Есть омега?" in sent and "Да, есть" in sent
    assert "Сделка создана" not in sent and "Оператор скоро ответит" not in sent


@pytest.mark.parametrize("kind", ["api_error", "timeout", "refusal", "max_tokens", "invalid_output"])
def test_llm_failure_returns_template(make_client, kind):
    llm = FakeLLMClient(error=LLMFailure(kind))
    response = make_client(llm).post("/v1/reply", json={"message": "Привет"})
    assert response.status_code == 200
    body = response.json()
    assert body["client_reply"] == FAILURE_REPLY_TEMPLATE
    assert body["needs_human"] is True and body["reason"] == "other"
    assert body["upsell"] == [] and body["used_kb_ids"] == []
    assert "Черновик не сформирован" in body["manager_hint"]


def test_direct_call_has_no_context(make_client):
    llm = FakeLLMClient(llm_output())
    make_client(llm).post("/v1/reply", json={"message": "Привет"})
    assert llm.calls[-1]["context"] is None


@pytest.mark.parametrize(
    "payload",
    [{"message": ""}, {"message": "Привет", "history": [{"role": "operator", "text": "x"}]}, {}],
)
def test_invalid_request(make_client, payload):
    llm = FakeLLMClient(llm_output())
    assert make_client(llm).post("/v1/reply", json=payload).status_code == 422
    assert llm.calls == []


def test_broken_kb_stops_startup(tmp_path, settings):
    raw = json.loads(settings.kb_path.read_text(encoding="utf-8"))
    raw["entries"].append(dict(raw["entries"][0]))
    broken = tmp_path / "kb.json"
    broken.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(KnowledgeBaseError, match="Повторяющийся id"):
        create_app(settings=Settings(_env_file=None, kb_path=broken), llm_client=FakeLLMClient())


def test_timeout_hint(make_client):
    body = make_client(FakeLLMClient(error=LLMFailure("timeout"))).post(
        "/v1/reply", json={"message": "Привет"}
    ).json()
    assert "модель не ответила за отведённое время (timeout)" in body["manager_hint"]
