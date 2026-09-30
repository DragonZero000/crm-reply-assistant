from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # OpenAI-совместимый API. По умолчанию — локальный LM Studio (ключ ему не нужен).
    llm_base_url: str = "http://127.0.0.1:1234/v1"
    llm_api_key: SecretStr = SecretStr("lm-studio")
    llm_model: str = "ornith-1.0-35b-mtp-apex"
    llm_max_tokens: int = Field(default=8000, gt=0)
    llm_timeout_seconds: float = Field(default=300.0, gt=0)
    # SDK по умолчанию повторяет запрос дважды, в том числе после таймаута: 300 с × 3.
    llm_max_retries: int = Field(default=0, ge=0)
    # Цены за 1 млн токенов для оценки стоимости в логе. Не заданы — cost=n/a
    # (локальная модель или модель на своих серверах, где цены за токен нет).
    llm_price_input_per_1m: float | None = Field(default=None, ge=0)
    llm_price_output_per_1m: float | None = Field(default=None, ge=0)

    @field_validator("llm_price_input_per_1m", "llm_price_output_per_1m", mode="before")
    @classmethod
    def _empty_price_is_unset(cls, value):
        # «LLM_PRICE_INPUT_PER_1M=» в .env значит «цена не задана», а не ошибка разбора.
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("llm_base_url")
    @classmethod
    def _default_api_prefix(cls, value: str) -> str:
        # «http://127.0.0.1:1234» → «http://127.0.0.1:1234/v1»: без пути LM Studio отвечает
        # 200 с {"error": "Unexpected endpoint"}, и это выглядит как пустой ответ модели.
        value = value.rstrip("/")
        return value + "/v1" if not urlsplit(value).path else value

    history_limit: int = Field(default=10, ge=0)
    kb_path: Path = PROJECT_ROOT / "data" / "knowledge_base.json"
    compliance_rules_path: Path = PROJECT_ROOT / "data" / "compliance_rules.json"

    # Адаптер AmoCRM. mock — примечания в памяти и страница /mock; amo — REST API amoCRM.
    crm_mode: Literal["mock", "amo"] = "mock"
    webhook_secret: SecretStr | None = None
    amo_subdomain: str | None = None
    amo_access_token: SecretStr | None = None

    @model_validator(mode="after")
    def _amo_settings_required(self) -> "Settings":
        if self.crm_mode == "amo":
            required = ("amo_subdomain", "amo_access_token", "webhook_secret")
            missing = [name.upper() for name in required if not _filled(getattr(self, name))]
            if missing:
                raise ValueError(f"CRM_MODE=amo: не заданы {', '.join(missing)}")
        return self


def _filled(value: str | SecretStr | None) -> bool:
    if isinstance(value, SecretStr):
        value = value.get_secret_value()
    return bool(value and value.strip())
