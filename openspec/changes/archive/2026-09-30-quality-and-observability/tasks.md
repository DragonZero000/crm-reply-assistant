## 1. Настройки

- [x] 1.1 Добавить в `Settings` поле `llm_max_retries: int` (`ge=0`, по умолчанию 0); `llm_timeout_seconds` оставить 300; тест значений по умолчанию
- [x] 1.2 Добавить `llm_price_input_per_1m` и `llm_price_output_per_1m: float | None` (`ge=0`, по умолчанию `None`); тест: отрицательная цена — ошибка валидации
- [x] 1.3 Добавить новые переменные в `.env.example` с комментариями: цены не заданы, для модели на своих серверах их не указывают; повторы для облачного провайдера — 1–2

## 2. Таймаут и повторы

- [x] 2.1 Передать `max_retries=settings.llm_max_retries` в `openai.OpenAI`; тест: клиент SDK создан с `max_retries=0` по умолчанию
- [x] 2.2 Ловить `openai.APITimeoutError` раньше `openai.APIError` → `LLMFailure("timeout")`; добавить случай в параметризацию `test_sdk_errors`
- [x] 2.3 В `_failure_response` для `kind="timeout"` писать «модель не ответила за отведённое время (timeout)», для остальных видов текст прежний; тест `/v1/reply` с `FakeLLMClient(error=LLMFailure("timeout"))`

## 3. Контекст вызова

- [x] 3.1 `CallContext(lead_id: int | None, message_id: str | None)` в `app/llm.py`; необязательный параметр `context` в протоколе `LLMClient.generate` и в `OpenAILLMClient.generate`
- [x] 3.2 `ReplyService.reply(request, exclude=..., context=None)` передаёт `context` в модель; `FakeLLMClient` запоминает `context` в `calls`
- [x] 3.3 `DialogAdapter.generate` передаёт `CallContext(event.lead_id, event.message_id)`; тест через вебхук: фейк получил `lead_id=555`, `message_id` сообщения
- [x] 3.4 Проверить, что `/v1/reply` вызывает модель без контекста и существующие тесты проходят без изменений

## 4. Лог вызова и стоимость

- [x] 4.1 Функция `estimate_cost(prompt_tokens, completion_tokens, price_in, price_out) -> float | None`; тесты: обе цены → `0.005` для 3000/500 при 1.0/4.0, одна цена → `None`, нет токенов → `None`
- [x] 4.2 В `OpenAILLMClient.generate` замер `time.perf_counter()` и одна строка `llm_call` в `finally` с полями `lead_id`, `message_id`, `model`, `outcome`, `latency_ms`, `prompt_tokens`, `completion_tokens`, `cost` (`n/a` для отсутствующих, `-` для пустого контекста); старую строку `llm id=…` заменить
- [x] 4.3 При `LengthFinishReasonError` брать токены из `exc.completion.usage`, если они есть
- [x] 4.4 Тесты через `caplog` и подмену SDK: успех (`outcome=ok`, токены, `cost=n/a` без цен), успех с ценами (`cost=0.005000`), таймаут (`outcome=timeout`, токены `n/a`), ответ без `usage`, неожиданное исключение (`outcome=client_error`); в каждом случае ровно одна строка `llm_call`
- [x] 4.5 Тест: ответ модели с `reason=no_kb_answer` даёт `outcome=ok`
- [x] 4.6 Тест: строка `llm_call` не содержит текста сообщения клиента и ключа API

## 5. Сценарии

- [x] 5.1 `tests/test_scenarios.py` с докстрингом «гарантии кода при заданном ответе модели; поведение модели — в test_live.py»
- [x] 5.2 Сценарии 1–2: вопрос по базе (upsell обогащён из базы, `needs_human=false`) и вопрос вне базы (`reason=no_kb_answer`)
- [x] 5.3 Сценарии 3–5: модель поддалась медицинской провокации (шаблон, `original_reply`, `reason=medical`, upsell пуст), медицинский вопрос с upsell (очищен), жалоба с upsell (очищен)
- [x] 5.4 Сценарий 6: `""` и `"   "` → 422, `llm.calls` пуст
- [x] 5.5 Сценарии 7–8: таймаут и битый ответ модели → 200, шаблон, вид сбоя в `manager_hint`, `used_kb_ids` пуст
- [x] 5.6 `uv run pytest` проходит целиком
- [x] 5.7 Исправить найденное сценарием 3: при срабатывании стоп-листа на `client_reply` (`reason` становится `medical`) очищать `upsell`, как требует спека `upsell-hints`; регрессионный тест в `test_service_compliance.py`

## 6. Документация

- [x] 6.1 README: таблица настроек дополнена `LLM_MAX_RETRIES`, `LLM_PRICE_INPUT_PER_1M`, `LLM_PRICE_OUTPUT_PER_1M`
- [x] 6.2 README, раздел «Логи и стоимость»: пример строки `llm_call`, формула стоимости, нагрузка прототипа (≈3,1 тыс. токенов промпта и ≈300 ответа на сообщение), оценка без учёта кэша префикса; `prompt_tokens` как замер для условия перехода на RAG
- [x] 6.3 README, раздел «Тесты»: юнит-тесты проверяют гарантии кода, live — поведение модели; ссылка на `tests/test_scenarios.py`
- [x] 6.4 README, раздел «Что улучшили бы дальше»: JSON-логи и метрики, алерты на долю шаблонных ответов, трейсинг, запасная модель и circuit breaker, бюджет на токены и rate limiting, eval-набор с проверкой фактов, кэш префикса и RAG по условиям из design.md
- [x] 6.5 Ручная проверка: запуск с недоступным `LLM_BASE_URL`, `POST /v1/reply` → 200 с шаблоном, в консоли одна строка `llm_call` с `outcome=api_error`
