from app.amo_webhook import ChatEvent
from app.dialogs import DialogStore


def event(message_id: str, text: str, role: str = "client", lead_id: int = 555) -> ChatEvent:
    return ChatEvent(message_id, lead_id, role, text)


def test_duplicate_returns_none():
    store = DialogStore()
    assert store.add(event("m1", "Привет")) == []
    assert store.add(event("m1", "Привет")) is None
    assert [m.text for m in store.messages(555)] == ["Привет"]


def test_history_before_message_excludes_it():
    store = DialogStore()
    store.add(event("m1", "Хочу Омега-3"))
    store.add(event("m2", "Она в наличии", role="manager"))
    history = store.add(event("m3", "А доставка в Казань?"))
    assert [(m.role, m.text) for m in history] == [("client", "Хочу Омега-3"), ("manager", "Она в наличии")]


def test_leads_are_separate_and_ordered():
    store = DialogStore()
    store.add(event("m1", "a", lead_id=555))
    store.add(event("m2", "b", lead_id=777))
    store.add(event("m3", "c", lead_id=555))
    assert [m.text for m in store.messages(555)] == ["a", "c"]
    assert [m.text for m in store.add(event("m4", "d", lead_id=777))] == ["b"]
    assert store.messages(999) == []


def test_offered_products():
    store = DialogStore()
    assert store.offered(555) == frozenset()
    store.remember_offered(555, {"vit_d3_2000"})
    store.remember_offered(555, {"magnesium_b6"})
    assert store.offered(555) == {"vit_d3_2000", "magnesium_b6"}
    assert store.offered(777) == frozenset()
