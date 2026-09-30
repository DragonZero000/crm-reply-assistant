from urllib.parse import urlencode

from app.llm import CallContext, LLMFailure, LLMOutputBase


class FakeLLMClient:
    """Возвращает заданный ответ (dict) или выбрасывает заданную ошибку; запоминает вызовы."""

    def __init__(self, output: dict | None = None, error: Exception | None = None):
        self.output = output
        self.error = error
        self.calls: list[dict] = []

    def generate(
        self,
        system_prompt: str,
        user_message: str,
        output_model: type[LLMOutputBase],
        context: CallContext | None = None,
    ):
        self.calls.append(
            {"system_prompt": system_prompt, "user_message": user_message, "context": context}
        )
        if self.error:
            raise self.error
        return output_model.model_validate(self.output)


def llm_output(**overrides) -> dict:
    base = {
        "client_reply": "Доставка до пункта выдачи стоит 290 ₽.",
        "used_kb_ids": ["faq_delivery"],
        "needs_human": False,
        "reason": None,
        "upsell": [],
        "manager_note": None,
    }
    base.update(overrides)
    return base


def amo_message(message_id: str, text: str, type: str = "incoming", lead_id: int | None = 555) -> dict:
    fields = {"id": message_id, "text": text, "type": type, "talk_id": "42"}
    if lead_id is not None:
        fields |= {"entity_type": "lead", "entity_id": str(lead_id)}
    return fields


def amo_body(*messages: dict) -> bytes:
    """Тело вебхука в формате amoCRM: message[add][N][поле]=значение."""
    pairs = [("account[subdomain]", "demo")]
    for index, fields in enumerate(messages):
        pairs += [(f"message[add][{index}][{key}]", value) for key, value in fields.items()]
    return urlencode(pairs).encode()


__all__ = ["FakeLLMClient", "LLMFailure", "amo_body", "amo_message", "llm_output"]
