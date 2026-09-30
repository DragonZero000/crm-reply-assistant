"""Допродажи: кандидаты из related_ids, проверка ответа модели, данные из базы."""

from dataclasses import dataclass

from app.kb import KnowledgeBase

MAX_UPSELL = 2
# При жалобе допродажа неуместна, при медицинском вопросе — ещё и опасна.
NO_UPSELL_REASONS = {"complaint", "medical"}


@dataclass(frozen=True)
class UpsellChoice:
    product_id: str
    why_now: str


def upsell_candidates(kb: KnowledgeBase, used_kb_ids: list[str]) -> set[str]:
    """related_ids карточек товаров из used_kb_ids, кроме самих этих товаров."""
    products = kb.products
    used_products = [products[i] for i in used_kb_ids if i in products]
    candidates = {rid for product in used_products for rid in product.related_ids}
    return candidates - {p.id for p in used_products}


def filter_upsell(
    kb: KnowledgeBase,
    used_kb_ids: list[str],
    choices: list[UpsellChoice],
    reason: str | None,
    exclude: frozenset[str] | set[str] = frozenset(),
) -> list[UpsellChoice]:
    """exclude — товары, которые уже предлагались в этом диалоге (их не повторяем)."""
    if reason in NO_UPSELL_REASONS:
        return []
    candidates = upsell_candidates(kb, used_kb_ids) - exclude
    result: list[UpsellChoice] = []
    seen: set[str] = set()
    for choice in choices:
        if choice.product_id not in candidates or choice.product_id in seen:
            continue
        seen.add(choice.product_id)
        result.append(choice)
        if len(result) == MAX_UPSELL:
            break
    return result
