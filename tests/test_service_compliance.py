from app.compliance import SAFE_REPLY_TEMPLATE
from app.schemas import ReplyRequest
from tests.fakes import FakeLLMClient, llm_output

REQUEST = ReplyRequest(message="Поможет ли омега от болей в суставах?")


def run(make_service, **overrides):
    return make_service(FakeLLMClient(llm_output(**overrides))).reply(REQUEST)


def test_reply_with_medical_claim_replaced(make_service):
    original = "Омега-3 избавит вас от болей в суставах."
    result = run(make_service, client_reply=original, used_kb_ids=["omega3_1000"])

    assert result.client_reply == SAFE_REPLY_TEMPLATE
    assert result.compliance.triggered is True
    assert result.compliance.original_reply == original
    reply_matches = [m for m in result.compliance.matches if m.field == "client_reply"]
    assert any("избавит" in m.fragment for m in reply_matches)
    assert (result.needs_human, result.reason) == (True, "medical")
    assert "избавит" in result.manager_hint


def test_complaint_reason_overridden_by_filter(make_service):
    result = run(
        make_service,
        client_reply="Извините! Новая банка вылечит ваше настроение.",
        needs_human=True,
        reason="complaint",
    )
    assert result.reason == "medical"
    assert result.client_reply == SAFE_REPLY_TEMPLATE


def test_upsell_why_now_with_claim_dropped(make_service):
    result = run(
        make_service,
        used_kb_ids=["omega3_1000"],
        upsell=[
            {"product_id": "vit_d3_2000", "why_now": "Витамин D гарантирует крепкий иммунитет."},
            {"product_id": "magnesium_b6", "why_now": "Упаковки хватает на тот же месяц."},
        ],
    )
    assert [u.product_id for u in result.upsell] == ["magnesium_b6"]
    assert result.client_reply == llm_output()["client_reply"]
    assert result.compliance.triggered is True
    assert {m.field for m in result.compliance.matches} == {"upsell.why_now"}
    assert result.compliance.original_reply is None
    assert result.needs_human is False


def test_manager_note_claim_only_flagged(make_service):
    result = run(make_service, manager_note="Скажите клиенту, что магний поможет от бессонницы.")
    assert result.client_reply == llm_output()["client_reply"]
    assert result.compliance.triggered is True
    assert {m.field for m in result.compliance.matches} == {"manager_note"}
    assert result.needs_human is False


def test_clean_reply_untouched(make_service):
    result = run(make_service)
    assert result.compliance.model_dump() == {"triggered": False, "matches": [], "original_reply": None}
    assert result.client_reply == llm_output()["client_reply"]


def test_reply_filter_clears_upsell(make_service):
    result = run(
        make_service,
        client_reply="Омега-3 избавит вас от болей в суставах.",
        used_kb_ids=["omega3_1000"],
        upsell=[{"product_id": "vit_d3_2000", "why_now": "Клиент берёт курс на месяц."}],
    )
    assert result.reason == "medical"
    assert result.upsell == []
    assert "Можно предложить" not in result.manager_hint
