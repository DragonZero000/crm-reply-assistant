"""Схема ответа модели и клиенты LLM."""

import logging
import time
from dataclasses import dataclass
from typing import Literal, Protocol

import openai
from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model, model_validator

from app.config import Settings
from app.kb import KnowledgeBase
from app.schemas import Reason

logger = logging.getLogger(__name__)


class LLMOutputBase(BaseModel):
    """Поля ответа модели, не зависящие от содержимого базы."""

    model_config = ConfigDict(extra="forbid")

    client_reply: str = Field(description="Черновик ответа клиенту, вежливый, только по базе знаний")
    needs_human: bool = Field(description="Нужно ли внимание менеджера")
    reason: Reason | None = Field(description="Причина передачи менеджеру; null, если needs_human=false")
    manager_note: str | None = Field(description="Короткая заметка для менеджера или null")

    @model_validator(mode="after")
    def _consistent_handoff(self):
        # reason=null тогда и только тогда, когда needs_human=false.
        if self.needs_human and self.reason is None:
            self.reason = "other"
        elif not self.needs_human and self.reason is not None:
            self.needs_human = True
        return self


def build_llm_output_model(kb: KnowledgeBase) -> type[LLMOutputBase]:
    """Схема ответа модели, где id записей и товаров ограничены значениями из базы."""
    kb_id = Literal[tuple(kb.entry_ids())]  # type: ignore[valid-type]
    product_id = Literal[tuple(kb.product_ids())]  # type: ignore[valid-type]

    upsell_model = create_model(
        "LLMUpsell",
        __config__=ConfigDict(extra="forbid"),
        product_id=(product_id, Field(description="id товара из «Можно предложить вместе с ним»")),
        why_now=(str, Field(description="Почему предложение уместно именно в этом диалоге")),
    )
    return create_model(
        "LLMOutput",
        __base__=LLMOutputBase,
        used_kb_ids=(list[kb_id], Field(description="id записей базы, на которых основан ответ")),
        upsell=(list[upsell_model], Field(description="0–2 допродажи для менеджера")),
    )


class LLMFailure(Exception):
    """Модель не дала пригодного ответа: отказ, обрыв, невалидный JSON, ошибка API."""

    def __init__(self, kind: str, detail: str = ""):
        super().__init__(f"{kind}: {detail}" if detail else kind)
        self.kind = kind
        self.detail = detail


@dataclass(frozen=True)
class CallContext:
    """Откуда пришёл вызов модели; попадает только в лог."""

    lead_id: int | None = None
    message_id: str | None = None


class LLMClient(Protocol):
    def generate(
        self,
        system_prompt: str,
        user_message: str,
        output_model: type[LLMOutputBase],
        context: CallContext | None = None,
    ) -> LLMOutputBase: ...


def estimate_cost(
    prompt_tokens: int | None,
    completion_tokens: int | None,
    price_input_per_1m: float | None,
    price_output_per_1m: float | None,
) -> float | None:
    """Оценка стоимости вызова; None, если неизвестны токены или хотя бы одна цена."""
    if None in (prompt_tokens, completion_tokens, price_input_per_1m, price_output_per_1m):
        return None
    return (prompt_tokens * price_input_per_1m + completion_tokens * price_output_per_1m) / 1_000_000


class OpenAILLMClient:
    """OpenAI-совместимый Chat Completions API (LM Studio, OpenAI и др.) со структурированным ответом."""

    def __init__(self, settings: Settings):
        self._client = openai.OpenAI(
            api_key=settings.llm_api_key.get_secret_value(),
            base_url=settings.llm_base_url,
            timeout=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
        )
        self._settings = settings

    def generate(
        self,
        system_prompt: str,
        user_message: str,
        output_model: type[LLMOutputBase],
        context: CallContext | None = None,
    ) -> LLMOutputBase:
        started = time.perf_counter()
        outcome, usage, model = "client_error", None, self._settings.llm_model
        try:
            try:
                completion = self._client.chat.completions.parse(
                    model=self._settings.llm_model,
                    max_tokens=self._settings.llm_max_tokens,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                    response_format=output_model,
                )
            except openai.LengthFinishReasonError as exc:
                # Обрезанный ответ — самый дорогой сбой: токены потрачены, поэтому их пишем.
                usage = getattr(getattr(exc, "completion", None), "usage", None)
                raise LLMFailure("max_tokens") from exc
            except openai.ContentFilterFinishReasonError as exc:
                raise LLMFailure("refusal", "content_filter") from exc
            except openai.APITimeoutError as exc:
                # Подкласс APIError: ловим раньше, чтобы таймаут не смешивался с ошибкой API.
                raise LLMFailure("timeout", str(exc)) from exc
            except openai.APIError as exc:
                raise LLMFailure("api_error", str(exc)) from exc
            except (ValidationError, ValueError) as exc:
                raise LLMFailure("invalid_output", str(exc)) from exc
            except Exception as exc:
                # CRM должна получить шаблон, а не 500, поэтому любая ошибка вызова — сбой модели.
                logger.exception("Unexpected error calling LLM")
                raise LLMFailure("client_error", str(exc)) from exc

            usage, model = completion.usage, completion.model or model
            if not completion.choices:
                raise LLMFailure("invalid_output", "пустой список choices")
            message = completion.choices[0].message
            if message.refusal:
                raise LLMFailure("refusal", message.refusal)
            if message.parsed is None:
                raise LLMFailure("invalid_output", "пустой parsed")
            if not message.parsed.client_reply.strip():
                # Без черновика менеджер должен видеть сбой, а не шаблон «уточню у специалиста».
                raise LLMFailure("invalid_output", "пустой client_reply")
            outcome = "ok"
            return message.parsed
        except LLMFailure as exc:
            outcome = exc.kind
            raise
        finally:
            self._log_call(context or CallContext(), model, outcome, started, usage)

    def _log_call(
        self, context: CallContext, model: str, outcome: str, started: float, usage
    ) -> None:
        # Текст сообщений и промпт не пишем: там персональные данные клиента.
        prompt_tokens = getattr(usage, "prompt_tokens", None)
        completion_tokens = getattr(usage, "completion_tokens", None)
        cost = estimate_cost(
            prompt_tokens,
            completion_tokens,
            self._settings.llm_price_input_per_1m,
            self._settings.llm_price_output_per_1m,
        )
        logger.info(
            "llm_call lead_id=%s message_id=%s model=%s outcome=%s latency_ms=%d "
            "prompt_tokens=%s completion_tokens=%s cost=%s",
            _or(context.lead_id, "-"),
            _or(context.message_id, "-"),
            model,
            outcome,
            (time.perf_counter() - started) * 1000,
            _or(prompt_tokens, "n/a"),
            _or(completion_tokens, "n/a"),
            "n/a" if cost is None else f"{cost:.6f}",
        )


def _or(value, placeholder: str):
    return placeholder if value is None else value
