"""История диалогов по сделкам в памяти процесса. После перезапуска теряется."""

from collections import defaultdict
from threading import Lock

from app.amo_webhook import ChatEvent
from app.schemas import HistoryMessage


class DialogStore:
    """Сообщения клиента и менеджера по lead_id, дедуп по id сообщения, выданные допродажи.

    Эндпоинт вебхука и фоновые задачи работают в разных потоках, поэтому всё под одной блокировкой.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._messages: dict[int, list[HistoryMessage]] = defaultdict(list)
        self._offered: dict[int, set[str]] = defaultdict(set)
        self._seen: set[str] = set()

    def add(self, event: ChatEvent) -> list[HistoryMessage] | None:
        """Добавляет сообщение и возвращает историю сделки до него; None — дубликат."""
        with self._lock:
            if event.message_id in self._seen:
                return None
            self._seen.add(event.message_id)
            messages = self._messages[event.lead_id]
            history = list(messages)
            messages.append(HistoryMessage(role=event.role, text=event.text))
            return history

    def messages(self, lead_id: int) -> list[HistoryMessage]:
        with self._lock:
            return list(self._messages.get(lead_id, []))

    def offered(self, lead_id: int) -> frozenset[str]:
        with self._lock:
            return frozenset(self._offered.get(lead_id, ()))

    def remember_offered(self, lead_id: int, product_ids: set[str]) -> None:
        with self._lock:
            self._offered[lead_id] |= product_ids
