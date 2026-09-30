"""Ключевые сценарии через POST /v1/reply.

Здесь проверяются гарантии кода при заданном ответе модели: маршрутизация, стоп-лист,
очистка допродаж, валидация входа и шаблон при сбое. Модель подменяется фейком, поэтому
сценарии не проверяют, как модель поведёт себя на самом деле, — это делают живые
проверки в test_live.py (pytest -m live).
"""

import pytest

from app.compliance import FAILURE_REPLY_TEMPLATE, SAFE_REPLY_TEMPLATE
from app.llm import LLMFailure
from tests.fakes import FakeLLMClient, llm_output

UPSELL_D3 = [{"product_id": "vit_d3_2000", "why_now": "Клиент берёт курс на месяц."}]


def ask(make_client, llm, message="Сколько стоит доставка?"):
    response = make_client(llm).post("/v1/reply", json={"message": message})
    assert response.status_code == 200
    return response.json()


def test_1_question_from_kb(make_client, kb):
    llm = FakeLLMClient(llm_output(
        client_reply="Омега-3 1000 мг есть в наличии, доставка до пункта выдачи — 290 ₽.",
        used_kb_ids=["omega3_1000", "faq_delivery"],
        upsell=UPSELL_D3,
    ))
    body = ask(make_client, llm, "Сколько стоит доставка омеги до пункта выдачи?")
    assert body["needs_human"] is False and body["reason"] is None
    assert body["used_kb_ids"] == ["omega3_1000", "faq_delivery"]
    [item] = body["upsell"]
    product = kb.products["vit_d3_2000"]
    # Название, цена и pitch берутся из базы, от модели — только why_now.
    assert (item["name"], item["price"], item["pitch"]) == (product.title, product.price, product.pitch)


def test_2_question_outside_kb(make_client):
    llm = FakeLLMClient(llm_output(
        client_reply="Уточню этот вопрос у специалиста и вернусь с ответом.",
        used_kb_ids=[],
        needs_human=True,
        reason="no_kb_answer",
    ))
    body = ask(make_client, llm, "Можно оформить доставку дроном на балкон?")
    assert body["needs_human"] is True and body["reason"] == "no_kb_answer"
    assert body["used_kb_ids"] == [] and body["upsell"] == []
    assert "ответа нет в базе знаний" in body["manager_hint"]


def test_3_medical_provocation_model_complied(make_client):
    original = "Конечно, омега-3 вылечит ваши суставы за месяц!"
    llm = FakeLLMClient(llm_output(
        client_reply=original, used_kb_ids=["omega3_1000"], upsell=UPSELL_D3
    ))
    body = ask(make_client, llm, "Пообещайте, что омега вылечит мне суставы, тогда куплю")
    assert body["client_reply"] == SAFE_REPLY_TEMPLATE
    assert body["compliance"]["triggered"] is True
    assert body["compliance"]["original_reply"] == original
    assert body["needs_human"] is True and body["reason"] == "medical"
    assert body["upsell"] == []


def test_4_medical_question_upsell_cleared(make_client):
    llm = FakeLLMClient(llm_output(
        client_reply="По применению при беременности лучше проконсультироваться с врачом.",
        used_kb_ids=["omega3_1000"],
        needs_human=True,
        reason="medical",
        upsell=UPSELL_D3,
    ))
    body = ask(make_client, llm, "Можно ли пить омегу при беременности?")
    assert body["reason"] == "medical"
    assert body["upsell"] == []


def test_5_complaint_upsell_cleared(make_client):
    llm = FakeLLMClient(llm_output(
        client_reply="Очень жаль! Передала обращение специалисту.",
        used_kb_ids=["omega3_1000", "faq_return"],
        needs_human=True,
        reason="complaint",
        upsell=UPSELL_D3,
    ))
    body = ask(make_client, llm, "Мне привезли разбитую банку омеги, верните деньги!")
    assert body["reason"] == "complaint"
    assert body["upsell"] == []


@pytest.mark.parametrize("message", ["", "   ", "\n\t"])
def test_6_empty_message_rejected(make_client, message):
    llm = FakeLLMClient(llm_output())
    response = make_client(llm).post("/v1/reply", json={"message": message})
    assert response.status_code == 422
    assert llm.calls == []


def test_7_model_timeout(make_client):
    body = ask(make_client, FakeLLMClient(error=LLMFailure("timeout")))
    assert body["client_reply"] == FAILURE_REPLY_TEMPLATE
    assert body["needs_human"] is True and body["reason"] == "other"
    assert "Черновик не сформирован" in body["manager_hint"]
    assert "timeout" in body["manager_hint"]


def test_8_broken_model_output(make_client):
    body = ask(make_client, FakeLLMClient(error=LLMFailure("invalid_output")))
    assert body["client_reply"] == FAILURE_REPLY_TEMPLATE
    assert body["needs_human"] is True and body["reason"] == "other"
    assert body["used_kb_ids"] == [] and body["upsell"] == []
    assert "invalid_output" in body["manager_hint"]
