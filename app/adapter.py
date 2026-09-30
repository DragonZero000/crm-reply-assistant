"""Адаптер диалога сделки: сообщения из вебхука → история → черновик → примечание к сделке."""

import logging

from app.amo_webhook import ChatEvent
from app.crm import CrmClient, CrmError
from app.dialogs import DialogStore
from app.llm import CallContext
from app.schemas import HistoryMessage, ReplyRequest, ReplyResponse
from app.service import ReplyService

logger = logging.getLogger(__name__)

Job = tuple[ChatEvent, list[HistoryMessage]]


class DialogAdapter:
    def __init__(self, service: ReplyService, store: DialogStore, crm: CrmClient):
        self.service = service
        self.store = store
        self.crm = crm

    def accept(self, events: list[ChatEvent]) -> list[Job]:
        """Пишет сообщения в историю; возвращает задания на генерацию для новых сообщений клиента."""
        jobs = []
        for event in events:
            history = self.store.add(event)
            if history is None:
                logger.info("Сообщение %s уже обработано, пропущено", event.message_id)
            elif event.role == "client":
                jobs.append((event, history))
        return jobs

    def generate(self, event: ChatEvent, history: list[HistoryMessage]) -> None:
        """Выполняется в фоне: вебхуку уже ответили, поэтому ошибки только логируются."""
        response = self.service.reply(
            ReplyRequest(message=event.text, history=history),
            exclude=self.store.offered(event.lead_id),
            context=CallContext(lead_id=event.lead_id, message_id=event.message_id),
        )
        try:
            self.crm.add_note(event.lead_id, format_note(response))
        except CrmError:
            logger.exception("Не удалось записать примечание к сделке %s", event.lead_id)
            return
        # Запоминаем только то, что менеджер действительно увидел в примечании.
        self.store.remember_offered(event.lead_id, {u.product_id for u in response.upsell})


def format_note(response: ReplyResponse) -> str:
    parts = ["Черновик ответа (не отправлен клиенту)", response.client_reply]
    if response.manager_hint:
        parts += ["", "Подсказка менеджеру", response.manager_hint]
    if response.compliance.original_reply:
        parts += [
            "",
            "Исходный черновик заблокирован фильтром медицинских формулировок:",
            response.compliance.original_reply,
        ]
    parts += ["", f"База знаний: {response.kb_version}"]
    return "\n".join(parts)
