from app.prompt import build_system_prompt
from app.schemas import ReplyRequest
from app.upsell import UpsellChoice, filter_upsell, upsell_candidates
from tests.fakes import FakeLLMClient, llm_output


def test_candidates_from_products(kb):
    assert upsell_candidates(kb, ["omega3_1000"]) == {"vit_d3_2000", "magnesium_b6"}


def test_candidates_exclude_used_products(kb):
    # omega3 и vit_d3 ссылаются друг на друга, но оба уже в ответе.
    assert upsell_candidates(kb, ["omega3_1000", "vit_d3_2000"]) == {"magnesium_b6"}


def test_faq_only_gives_no_candidates(kb):
    assert upsell_candidates(kb, ["faq_delivery", "faq_payment"]) == set()


def test_product_without_related_gives_no_candidates(kb):
    assert upsell_candidates(kb, ["probiotic_10"]) == set()


def test_filter_drops_non_candidates_duplicates_and_extra(kb):
    choices = [
        UpsellChoice("zinc_15", "не кандидат"),
        UpsellChoice("vit_d3_2000", "первый"),
        UpsellChoice("vit_d3_2000", "дубль"),
        UpsellChoice("magnesium_b6", "второй"),
    ]
    result = filter_upsell(kb, ["omega3_1000", "faq_delivery"], choices, None)
    assert [(c.product_id, c.why_now) for c in result] == [("vit_d3_2000", "первый"), ("magnesium_b6", "второй")]


def test_filter_limit_two(kb):
    choices = [UpsellChoice("vit_d3_2000", "a"), UpsellChoice("magnesium_b6", "b")]
    # Три кандидата недостижимы в реальной базе, поэтому проверяем, что больше двух не бывает.
    assert len(filter_upsell(kb, ["omega3_1000"], choices * 2, None)) == 2


def test_complaint_and_medical_clear_upsell(kb):
    choices = [UpsellChoice("vit_d3_2000", "a")]
    assert filter_upsell(kb, ["omega3_1000"], choices, "complaint") == []
    assert filter_upsell(kb, ["omega3_1000"], choices, "medical") == []


def test_service_enriches_from_kb(make_service, kb):
    llm = FakeLLMClient(llm_output(
        used_kb_ids=["omega3_1000"],
        upsell=[{"product_id": "vit_d3_2000", "why_now": "Клиент берёт курс на месяц."}],
    ))
    result = make_service(llm).reply(ReplyRequest(message="Что в составе омеги?"))
    product = kb.products["vit_d3_2000"]
    assert [u.model_dump() for u in result.upsell] == [{
        "product_id": "vit_d3_2000",
        "name": product.title,
        "price": product.price,
        "pitch": product.pitch,
        "why_now": "Клиент берёт курс на месяц.",
    }]


def test_filter_drops_excluded(kb):
    choices = [UpsellChoice("vit_d3_2000", "a"), UpsellChoice("magnesium_b6", "b")]
    result = filter_upsell(kb, ["omega3_1000"], choices, None, exclude={"vit_d3_2000"})
    assert [c.product_id for c in result] == ["magnesium_b6"]


def test_filter_all_candidates_excluded(kb):
    choices = [UpsellChoice("vit_d3_2000", "a"), UpsellChoice("magnesium_b6", "b")]
    assert filter_upsell(kb, ["omega3_1000"], choices, None, exclude={"vit_d3_2000", "magnesium_b6"}) == []


def test_service_passes_exclude(make_service):
    llm = FakeLLMClient(llm_output(
        used_kb_ids=["omega3_1000"],
        upsell=[{"product_id": "vit_d3_2000", "why_now": "Курс на месяц."}],
    ))
    service = make_service(llm)
    request = ReplyRequest(message="Что в составе омеги?")
    assert [u.product_id for u in service.reply(request).upsell] == ["vit_d3_2000"]
    result = service.reply(request, exclude=frozenset({"vit_d3_2000"}))
    assert result.upsell == []
    assert "Можно предложить" not in result.manager_hint


def test_prompt_forbids_repeating_manager_offers(kb):
    assert "менеджер уже предлагал клиенту в истории" in build_system_prompt(kb)
