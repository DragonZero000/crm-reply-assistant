from app.schemas import Compliance, ComplianceMatch, UpsellItem
from app.service import build_manager_hint


def test_hint_with_upsell():
    item = UpsellItem(product_id="p", name="Витамин D3", price=690, pitch="Часто берут вместе.", why_now="Курс на месяц.")
    hint = build_manager_hint(False, None, None, Compliance(), [item])
    assert "Витамин D3 — 690 ₽ — Часто берут вместе. — Курс на месяц." in hint
    assert "Нужен менеджер" not in hint


def test_hint_with_handoff_note_and_filter():
    compliance = Compliance(
        triggered=True,
        matches=[ComplianceMatch(field="client_reply", fragment="избавит от", rule_id="rid_of")],
        original_reply="...",
    )
    hint = build_manager_hint(True, "no_kb_answer", "Спросил про самовывоз.", compliance, [])
    assert "Нужен менеджер: ответа нет в базе знаний." in hint
    assert "Заметка: Спросил про самовывоз." in hint
    assert "«избавит от»" in hint and "заменён шаблоном" in hint


def test_empty_hint():
    assert build_manager_hint(False, None, None, Compliance(), []) == ""
