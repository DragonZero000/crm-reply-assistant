"""Контракт HTTP API."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

Role = Literal["client", "manager", "bot", "system"]
Reason = Literal["medical", "no_kb_answer", "complaint", "other"]
NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class HistoryMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Role
    text: NonEmptyText


class ReplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: NonEmptyText
    history: list[HistoryMessage] = []


class UpsellItem(BaseModel):
    product_id: str
    name: str
    price: int
    pitch: str
    why_now: str


class ComplianceMatch(BaseModel):
    field: str
    fragment: str
    rule_id: str


class Compliance(BaseModel):
    triggered: bool = False
    matches: list[ComplianceMatch] = []
    original_reply: str | None = None


class ReplyResponse(BaseModel):
    client_reply: NonEmptyText
    manager_hint: str
    used_kb_ids: list[str]
    needs_human: bool
    reason: Reason | None
    upsell: list[UpsellItem]
    compliance: Compliance
    kb_version: str
