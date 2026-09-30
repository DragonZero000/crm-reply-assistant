"""Разбор вебхука amoCRM о новых сообщениях в чате (application/x-www-form-urlencoded).

Формат приближен к событию amoCRM: message[add][N][id|text|type|entity_type|entity_id|…],
message[add][N][author][…], account[…]. Перед подключением реального аккаунта сверить
с живым payload (см. design.md, «Как подключить реальную amoCRM»).
"""

import logging
import re
from dataclasses import dataclass
from urllib.parse import parse_qsl

from app.schemas import Role

logger = logging.getLogger(__name__)

MESSAGE_KEY = re.compile(r"^message\[add\]\[(\d+)\]\[(\w+)\]$")
ROLES: dict[str, Role] = {"incoming": "client", "outgoing": "manager"}


@dataclass(frozen=True)
class ChatEvent:
    message_id: str
    lead_id: int
    role: Role
    text: str


def parse_amo_webhook(body: bytes) -> list[ChatEvent]:
    """Сообщения из тела вебхука в порядке индексов; непригодные пропускаются с записью в лог."""
    messages: dict[int, dict[str, str]] = {}
    for key, value in parse_qsl(body.decode("utf-8", errors="replace"), keep_blank_values=True):
        # Вложенные поля (author[…]) адаптеру не нужны и сюда не попадают.
        match = MESSAGE_KEY.match(key)
        if match:
            messages.setdefault(int(match[1]), {})[match[2]] = value

    events = []
    for index in sorted(messages):
        event, problem = _to_event(messages[index])
        if event:
            events.append(event)
        else:
            logger.info("Сообщение message[add][%d] пропущено: %s", index, problem)
    return events


def _to_event(fields: dict[str, str]) -> tuple[ChatEvent | None, str]:
    message_id = fields.get("id", "").strip()
    if not message_id:
        return None, "нет id сообщения"
    if fields.get("entity_type") != "lead" or not fields.get("entity_id", "").isdigit():
        return None, f"сообщение {message_id} не привязано к сделке"
    role = ROLES.get(fields.get("type", ""))
    if role is None:
        return None, f"неизвестный тип {fields.get('type')!r} у сообщения {message_id}"
    text = fields.get("text", "").strip()
    if not text:
        return None, f"пустой текст у сообщения {message_id}"
    return ChatEvent(message_id, int(fields["entity_id"]), role, text), ""
