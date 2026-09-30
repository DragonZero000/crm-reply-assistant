from pathlib import Path

from app.amo_webhook import ChatEvent, parse_amo_webhook
from tests.fakes import amo_body, amo_message

FIXTURES = Path(__file__).parent / "fixtures"


def test_fixture_incoming_message():
    events = parse_amo_webhook((FIXTURES / "amo_incoming.txt").read_bytes())
    assert events == [ChatEvent(
        message_id="5f1c2a9e-0d5b-4a53-9a0e-7a1c9b2f3e10",
        lead_id=555,
        role="client",
        text="А доставка в Казань сколько идёт?",
    )]


def test_outgoing_is_manager():
    [event] = parse_amo_webhook(amo_body(amo_message("m1", "Она в наличии", type="outgoing")))
    assert event.role == "manager"


def test_several_messages_in_index_order():
    body = amo_body(amo_message("m1", "Первое"), amo_message("m2", "Второе", type="outgoing"))
    assert [(e.message_id, e.role) for e in parse_amo_webhook(body)] == [("m1", "client"), ("m2", "manager")]


def test_indexes_sorted_numerically():
    # Индекс 10 в теле раньше индекса 2: порядок по числу, а не по строке и не по месту в теле.
    parts = [
        amo_body(amo_message(f"m{index}", "текст")).decode().replace("%5B0%5D", f"%5B{index}%5D")
        for index in (10, 2)
    ]
    assert [e.message_id for e in parse_amo_webhook("&".join(parts).encode())] == ["m2", "m10"]


def test_message_without_lead_skipped(caplog):
    caplog.set_level("INFO")
    body = amo_body(amo_message("m1", "Без сделки", lead_id=None), amo_message("m2", "Есть сделка"))
    assert [e.message_id for e in parse_amo_webhook(body)] == ["m2"]
    assert "не привязано к сделке" in caplog.text


def test_contact_entity_skipped():
    message = amo_message("m1", "Привет") | {"entity_type": "contact"}
    assert parse_amo_webhook(amo_body(message)) == []


def test_empty_text_skipped():
    assert parse_amo_webhook(amo_body(amo_message("m1", "   "))) == []


def test_unknown_type_skipped():
    assert parse_amo_webhook(amo_body(amo_message("m1", "Привет", type="system"))) == []


def test_missing_id_skipped():
    assert parse_amo_webhook(amo_body(amo_message("", "Привет"))) == []


def test_garbage_body():
    assert parse_amo_webhook(b"\xff\xfe not a form") == []
