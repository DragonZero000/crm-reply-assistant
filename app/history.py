"""Подготовка истории диалога для модели."""

import re

from app.schemas import HistoryMessage

MODEL_ROLES = {"client", "manager"}
ROLE_LABELS = {"client": "клиент", "manager": "менеджер"}

_LINE_BREAK = re.compile(r"\r\n|\r|\n")


def prepare_history(history: list[HistoryMessage], limit: int) -> list[HistoryMessage]:
    """Оставляет только клиента и менеджера, затем последние `limit` сообщений."""
    relevant = [m for m in history if m.role in MODEL_ROLES]
    return relevant[-limit:] if limit > 0 else []


def escape_text(text: str) -> str:
    """Структуру расшифровки задаёт только код: текст не может закрыть тег или начать строку с роли."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return _LINE_BREAK.sub(" ", text)


def build_transcript(history: list[HistoryMessage], new_message: str) -> str:
    lines = []
    if history:
        lines.append("<history>")
        lines.extend(f"[{ROLE_LABELS[m.role]}]: {escape_text(m.text)}" for m in history)
        lines.append("</history>")
    lines.append("<new_message>")
    lines.append(escape_text(new_message))
    lines.append("</new_message>")
    return "\n".join(lines)
