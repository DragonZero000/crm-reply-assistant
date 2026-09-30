## ADDED Requirements

### Requirement: Лог каждого вызова модели
Система SHALL записывать ровно одну строку лога `llm_call` уровня INFO на каждый вызов модели, при успехе и при любом сбое. Строка MUST содержать поля `model`, `outcome` (`ok` или вид сбоя: `timeout`, `api_error`, `refusal`, `max_tokens`, `invalid_output`, `client_error`), `latency_ms`, `prompt_tokens`, `completion_tokens`, `cost`. Если провайдер не вернул число токенов, поле MUST иметь значение `n/a`. Лог MUST NOT содержать текст сообщений клиента, промпт и ответ модели, а также ключ API.

#### Scenario: Успешный вызов
- **GIVEN** модель вернула ответ, `usage` содержит 3100 токенов промпта и 280 токенов ответа
- **WHEN** сервис обрабатывает `POST /v1/reply`
- **THEN** в логе одна строка `llm_call` с `outcome=ok`, `prompt_tokens=3100`, `completion_tokens=280` и `latency_ms` не меньше нуля

#### Scenario: Ответа нет в базе знаний
- **GIVEN** модель корректно вернула `needs_human=true`, `reason=no_kb_answer`
- **WHEN** сервис обрабатывает запрос
- **THEN** строка `llm_call` имеет `outcome=ok`: передача менеджеру — штатный результат вызова, а не сбой модели

#### Scenario: Сбой вызова
- **GIVEN** вызов модели завершился таймаутом
- **WHEN** сервис обрабатывает запрос
- **THEN** в логе одна строка `llm_call` с `outcome=timeout`, заполненным `latency_ms` и `prompt_tokens=n/a`, `completion_tokens=n/a`, `cost=n/a`

#### Scenario: Провайдер не вернул usage
- **GIVEN** модель вернула ответ без поля `usage`
- **WHEN** сервис записывает лог
- **THEN** строка `llm_call` содержит `prompt_tokens=n/a`, `completion_tokens=n/a`, `cost=n/a`, ответ клиенту формируется как обычно

### Requirement: Оценка стоимости вызова
Система SHALL считать оценку стоимости вызова по формуле `prompt_tokens × LLM_PRICE_INPUT_PER_1M / 1 000 000 + completion_tokens × LLM_PRICE_OUTPUT_PER_1M / 1 000 000`, только когда обе цены заданы в настройках и провайдер вернул число токенов. Цены по умолчанию не заданы, и тогда `cost=n/a`. Система MUST NOT содержать встроенных цен конкретных моделей. Цены MUST быть неотрицательными: иначе сервис не запускается.

#### Scenario: Цены заданы
- **GIVEN** `LLM_PRICE_INPUT_PER_1M=1.0`, `LLM_PRICE_OUTPUT_PER_1M=4.0`, вызов израсходовал 3000 токенов промпта и 500 токенов ответа
- **WHEN** сервис записывает лог
- **THEN** строка `llm_call` содержит `cost=0.005000`

#### Scenario: Цены не заданы
- **GIVEN** цены в `.env` не указаны (локальная модель или модель на серверах компании)
- **WHEN** сервис записывает лог успешного вызова
- **THEN** токены записаны, `cost=n/a`

#### Scenario: Задана только одна цена
- **GIVEN** задана только `LLM_PRICE_INPUT_PER_1M`
- **WHEN** сервис записывает лог
- **THEN** `cost=n/a`: неполная оценка вводила бы в заблуждение

### Requirement: Контекст сделки в логе вызова
Когда вызов модели запущен сообщением из вебхука, строка `llm_call` SHALL содержать `lead_id` и `message_id` этого сообщения. Для прямого вызова `POST /v1/reply` эти поля MUST иметь значение `-`.

#### Scenario: Вызов из вебхука
- **GIVEN** вебхук принёс сообщение клиента `msg-1` по сделке 555
- **WHEN** в фоне генерируется черновик
- **THEN** строка `llm_call` содержит `lead_id=555` и `message_id=msg-1`

#### Scenario: Прямой вызов API
- **GIVEN** работающий сервис
- **WHEN** приходит `POST /v1/reply`
- **THEN** строка `llm_call` содержит `lead_id=-` и `message_id=-`
