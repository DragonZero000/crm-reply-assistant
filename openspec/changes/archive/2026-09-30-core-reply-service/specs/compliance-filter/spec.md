## ADDED Requirements

### Requirement: Стоп-лист медицинских обещаний
Система SHALL читать правила из `compliance_rules.json`; каждое правило имеет `rule_id`, регулярное выражение по фразе (не по голой основе слова) и описание. Перед проверкой текст MUST приводиться к нижнему регистру, `ё` MUST заменяться на `е`.

#### Scenario: Срабатывание на запрещённую формулировку
- **GIVEN** правило, ловящее «вылечит» и его формы
- **WHEN** проверяется текст «Этот комплекс ВЫЛЕЧИТ суставы»
- **THEN** правило срабатывает, в результате есть `rule_id` и найденный фрагмент

#### Scenario: Обязательная оговорка не срабатывает
- **GIVEN** загруженный стоп-лист
- **WHEN** проверяется текст «Не является лекарственным средством»
- **THEN** срабатываний нет

### Requirement: Замена черновика ответа клиенту
Если стоп-лист сработал на `client_reply`, система SHALL заменить `client_reply` безопасным шаблоном, сохранить исходный текст в `compliance.original_reply`, установить `needs_human=true` и `reason=medical`, `compliance.triggered=true`, и перечислить совпадения в `compliance.matches` как `{field, fragment, rule_id}`.

#### Scenario: Модель пообещала лечебный эффект
- **GIVEN** модель вернула `client_reply` «Омега-3 избавит вас от болей в суставах», `needs_human=false`
- **WHEN** сервис применяет стоп-лист
- **THEN** `client_reply` равен безопасному шаблону, `compliance.original_reply` содержит исходный текст, `compliance.matches` содержит `{field: "client_reply", fragment: "избавит", rule_id: ...}`, `needs_human=true`, `reason=medical`

#### Scenario: Жалоба с медицинским обещанием
- **GIVEN** модель вернула `reason=complaint`, и стоп-лист сработал на `client_reply`
- **WHEN** сервис применяет стоп-лист
- **THEN** `reason=medical`, `client_reply` равен шаблону

#### Scenario: Чистый ответ
- **GIVEN** `client_reply` без запрещённых формулировок
- **WHEN** сервис применяет стоп-лист
- **THEN** `compliance.triggered=false`, `matches` пуст, `original_reply=null`, `client_reply` не изменён

### Requirement: Проверка допродаж и заметки менеджеру
Система SHALL проверять стоп-листом `why_now` каждой позиции `upsell` и `manager_note`. Позиция `upsell` со срабатыванием MUST быть удалена; срабатывание в `manager_note` MUST только отражаться в `compliance.matches` без замены `client_reply`. В обоих случаях `compliance.triggered=true`.

#### Scenario: Медицинское обещание в обосновании допродажи
- **GIVEN** модель вернула допродажу с `why_now` «витамин D гарантирует крепкий иммунитет» и чистый `client_reply`
- **WHEN** сервис применяет стоп-лист
- **THEN** эта позиция удалена из `upsell`, `compliance.matches` содержит `{field: "upsell.why_now", ...}`, `client_reply` не изменён

### Requirement: Прозрачность для менеджера
При `compliance.triggered=true` система SHALL добавить в `manager_hint` строку о том, что сработал фильтр медицинских формулировок, с найденными фрагментами.

#### Scenario: Менеджер видит причину замены
- **GIVEN** стоп-лист сработал на `client_reply` по фрагменту «избавит»
- **WHEN** сервис формирует `manager_hint`
- **THEN** `manager_hint` сообщает о замене черновика и содержит фрагмент «избавит»

### Requirement: Шаблоны проходят стоп-лист
Безопасный шаблон ответа и шаблон ответа при сбое модели MUST NOT вызывать срабатывание стоп-листа.

#### Scenario: Проверка шаблонов
- **GIVEN** загруженный стоп-лист
- **WHEN** проверяются тексты обоих шаблонов
- **THEN** срабатываний нет
