"""Пайплайн: история → модель → допродажи → стоп-лист → ответ сервиса."""

import logging

from app.compliance import FAILURE_REPLY_TEMPLATE, SAFE_REPLY_TEMPLATE, StopList
from app.history import build_transcript, prepare_history
from app.kb import KnowledgeBase
from app.llm import CallContext, LLMClient, LLMFailure, LLMOutputBase, build_llm_output_model
from app.prompt import build_system_prompt
from app.schemas import (
    Compliance,
    ComplianceMatch,
    ReplyRequest,
    ReplyResponse,
    UpsellItem,
)
from app.upsell import UpsellChoice, filter_upsell

logger = logging.getLogger(__name__)

REASON_LABELS = {
    "medical": "медицинский вопрос",
    "no_kb_answer": "ответа нет в базе знаний",
    "complaint": "жалоба",
    "other": "другое",
}


class ReplyService:
    def __init__(self, kb: KnowledgeBase, stop_list: StopList, llm: LLMClient, history_limit: int):
        self.kb = kb
        self.stop_list = stop_list
        self.llm = llm
        self.history_limit = history_limit
        self.system_prompt = build_system_prompt(kb)
        self.output_model = build_llm_output_model(kb)

    def reply(
        self,
        request: ReplyRequest,
        exclude: frozenset[str] = frozenset(),
        context: CallContext | None = None,
    ) -> ReplyResponse:
        """exclude — product_id, которые уже предлагались по этой сделке; в upsell не попадут.
        context — сделка и сообщение, из-за которых вызвана модель; нужен только для лога."""
        history = prepare_history(request.history, self.history_limit)
        transcript = build_transcript(history, request.message)
        try:
            output = self.llm.generate(self.system_prompt, transcript, self.output_model, context)
        except LLMFailure as exc:
            logger.warning("LLM failure: %s", exc)
            return self._failure_response(exc.kind)
        return self._build_response(output, exclude)

    def _build_response(self, output: LLMOutputBase, exclude: frozenset[str]) -> ReplyResponse:
        used_kb_ids = list(dict.fromkeys(output.used_kb_ids))  # type: ignore[attr-defined]
        needs_human, reason = output.needs_human, output.reason
        client_reply = output.client_reply.strip() or SAFE_REPLY_TEMPLATE
        manager_note = output.manager_note

        choices = [UpsellChoice(u.product_id, u.why_now) for u in output.upsell]  # type: ignore[attr-defined]
        choices = filter_upsell(self.kb, used_kb_ids, choices, reason, exclude)

        compliance = Compliance()

        reply_matches = self.stop_list.check(client_reply)
        if reply_matches:
            compliance.original_reply = client_reply
            client_reply = SAFE_REPLY_TEMPLATE
            needs_human, reason = True, "medical"
            # filter_upsell видел причину от модели; при medical допродажа неуместна в любом случае.
            choices = []
            compliance.matches += [
                ComplianceMatch(field="client_reply", fragment=m.fragment, rule_id=m.rule_id)
                for m in reply_matches
            ]

        kept_choices = []
        for choice in choices:
            matches = self.stop_list.check(choice.why_now)
            if matches:
                compliance.matches += [
                    ComplianceMatch(field="upsell.why_now", fragment=m.fragment, rule_id=m.rule_id)
                    for m in matches
                ]
            else:
                kept_choices.append(choice)

        if manager_note:
            compliance.matches += [
                ComplianceMatch(field="manager_note", fragment=m.fragment, rule_id=m.rule_id)
                for m in self.stop_list.check(manager_note)
            ]

        compliance.triggered = bool(compliance.matches)
        upsell = [self._enrich(choice) for choice in kept_choices]

        return ReplyResponse(
            client_reply=client_reply,
            manager_hint=build_manager_hint(needs_human, reason, manager_note, compliance, upsell),
            used_kb_ids=used_kb_ids,
            needs_human=needs_human,
            reason=reason,
            upsell=upsell,
            compliance=compliance,
            kb_version=self.kb.version,
        )

    def _enrich(self, choice: UpsellChoice) -> UpsellItem:
        product = self.kb.products[choice.product_id]
        return UpsellItem(
            product_id=product.id,
            name=product.title,
            price=product.price,
            pitch=product.pitch,
            why_now=choice.why_now,
        )

    def _failure_response(self, kind: str) -> ReplyResponse:
        cause = (
            "модель не ответила за отведённое время (timeout)"
            if kind == "timeout"
            else f"сбой модели ({kind})"
        )
        return ReplyResponse(
            client_reply=FAILURE_REPLY_TEMPLATE,
            manager_hint=f"Черновик не сформирован: {cause}. Ответ клиенту — шаблон, ответьте вручную.",
            used_kb_ids=[],
            needs_human=True,
            reason="other",
            upsell=[],
            compliance=Compliance(),
            kb_version=self.kb.version,
        )


def build_manager_hint(
    needs_human: bool,
    reason: str | None,
    manager_note: str | None,
    compliance: Compliance,
    upsell: list[UpsellItem],
) -> str:
    lines = []
    if needs_human and reason:
        lines.append(f"Нужен менеджер: {REASON_LABELS[reason]}.")
    if manager_note:
        lines.append(f"Заметка: {manager_note}")
    if compliance.triggered:
        by_field: dict[str, list[str]] = {}
        for match in compliance.matches:
            by_field.setdefault(match.field, []).append(f"«{match.fragment}»")
        actions = {
            "client_reply": "черновик ответа заменён шаблоном, исходный текст — в compliance.original_reply",
            "upsell.why_now": "допродажа убрана",
            "manager_note": "в заметке для менеджера, не повторяйте клиенту",
        }
        for field, fragments in by_field.items():
            lines.append(
                f"Фильтр медицинских формулировок ({', '.join(fragments)}): {actions[field]}."
            )
    if upsell:
        lines.append("Можно предложить:")
        lines.extend(f"- {u.name} — {u.price} ₽ — {u.pitch} — {u.why_now}" for u in upsell)
    return "\n".join(lines)
