import json

import httpx
import pytest

from app.adapter import format_note
from app.crm import AmoCrmClient, CrmError, MockCrmClient
from app.schemas import Compliance, ComplianceMatch, ReplyResponse, UpsellItem


def test_mock_client_stores_notes():
    crm = MockCrmClient()
    crm.add_note(555, "первое")
    crm.add_note(555, "второе")
    crm.add_note(777, "другое")
    assert [n.text for n in crm.notes(555)] == ["первое", "второе"]
    assert crm.notes(999) == []


def amo_client(handler) -> AmoCrmClient:
    return AmoCrmClient("demo", "tkn", transport=httpx.MockTransport(handler))


def test_amo_client_request():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"_embedded": {"notes": [{"id": 1}]}})

    amo_client(handler).add_note(555, "Черновик")
    [request] = seen
    assert request.method == "POST"
    assert str(request.url) == "https://demo.amocrm.ru/api/v4/leads/555/notes"
    assert request.headers["Authorization"] == "Bearer tkn"
    assert json.loads(request.content) == [{"note_type": "common", "params": {"text": "Черновик"}}]


def test_amo_client_full_host():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={})

    AmoCrmClient("demo.kommo.com", "tkn", transport=httpx.MockTransport(handler)).add_note(1, "x")
    assert seen[0].url.host == "demo.kommo.com"


@pytest.mark.parametrize("status", [401, 500])
def test_amo_client_error_status(status):
    with pytest.raises(CrmError, match=str(status)) as info:
        amo_client(lambda request: httpx.Response(status)).add_note(555, "x")
    assert "tkn" not in str(info.value)


def test_amo_client_network_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    with pytest.raises(CrmError):
        amo_client(handler).add_note(555, "x")


def response(**overrides) -> ReplyResponse:
    base = dict(
        client_reply="Доставка в Казань занимает от 2 до 7 рабочих дней.",
        manager_hint="",
        used_kb_ids=["faq_delivery"],
        needs_human=False,
        reason=None,
        upsell=[],
        compliance=Compliance(),
        kb_version="2026-09-30.2",
    )
    return ReplyResponse(**(base | overrides))


def test_note_with_upsell():
    item = UpsellItem(product_id="vit_d3_2000", name="Витамин D3", price=690, pitch="p", why_now="Курс на месяц.")
    note = format_note(response(
        upsell=[item], manager_hint="Можно предложить:\n- Витамин D3 — 690 ₽ — p — Курс на месяц."
    ))
    assert note.startswith("Черновик ответа (не отправлен клиенту)\nДоставка в Казань")
    assert "Подсказка менеджеру\nМожно предложить:" in note
    assert "Витамин D3 — 690 ₽" in note and "Курс на месяц." in note
    assert note.endswith("База знаний: 2026-09-30.2")


def test_note_without_hint_has_no_hint_section():
    assert "Подсказка менеджеру" not in format_note(response())


def test_note_no_kb_answer():
    note = format_note(response(
        client_reply="Уточню у специалиста и вернусь с ответом.",
        manager_hint="Нужен менеджер: ответа нет в базе знаний.",
        needs_human=True,
        reason="no_kb_answer",
    ))
    assert "Нужен менеджер: ответа нет в базе знаний." in note


def test_note_shows_blocked_original():
    compliance = Compliance(
        triggered=True,
        matches=[ComplianceMatch(field="client_reply", fragment="вылечит", rule_id="cure")],
        original_reply="Омега вылечит суставы.",
    )
    note = format_note(response(compliance=compliance, needs_human=True, reason="medical"))
    assert "Исходный черновик заблокирован фильтром медицинских формулировок:\nОмега вылечит суставы." in note
