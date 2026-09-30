"""Исходящая сторона интеграции: запись примечания к сделке."""

from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock
from typing import Protocol

import httpx


class CrmError(Exception):
    """Не удалось записать примечание в CRM."""


class CrmClient(Protocol):
    def add_note(self, lead_id: int, text: str) -> None: ...


@dataclass(frozen=True)
class Note:
    text: str
    created_at: datetime


class MockCrmClient:
    """Режим по умолчанию: примечания хранятся в памяти и видны на странице /mock."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._notes: dict[int, list[Note]] = {}

    def add_note(self, lead_id: int, text: str) -> None:
        with self._lock:
            self._notes.setdefault(lead_id, []).append(Note(text, datetime.now(UTC)))

    def notes(self, lead_id: int) -> list[Note]:
        with self._lock:
            return list(self._notes.get(lead_id, []))


class AmoCrmClient:
    """REST API amoCRM v4 с долгосрочным токеном приватной интеграции.

    Проверен только тестами с подменой транспорта, не на живом аккаунте.
    """

    def __init__(
        self,
        subdomain: str,
        access_token: str,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 10.0,
    ) -> None:
        # «demo» → demo.amocrm.ru; полный хост (например, для kommo.com) передаётся как есть.
        host = subdomain if "." in subdomain else f"{subdomain}.amocrm.ru"
        self._client = httpx.Client(
            base_url=f"https://{host}",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=timeout,
            transport=transport,
        )

    def add_note(self, lead_id: int, text: str) -> None:
        payload = [{"note_type": "common", "params": {"text": text}}]
        try:
            response = self._client.post(f"/api/v4/leads/{lead_id}/notes", json=payload)
        except httpx.HTTPError as exc:
            raise CrmError(f"amoCRM недоступна: {type(exc).__name__}") from exc
        if response.is_error:
            raise CrmError(f"amoCRM ответила {response.status_code} на примечание к сделке {lead_id}")
