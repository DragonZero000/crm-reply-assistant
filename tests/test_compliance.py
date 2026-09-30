import json

import pytest

from app.compliance import (
    FAILURE_REPLY_TEMPLATE,
    SAFE_REPLY_TEMPLATE,
    ComplianceRulesError,
    load_stop_list,
)


def test_rules_file_loads(settings, stop_list):
    raw = json.loads(settings.compliance_rules_path.read_text(encoding="utf-8"))
    ids = [r["rule_id"] for r in raw["rules"]]
    assert len(ids) == len(set(ids)) == len(stop_list.rules)


def test_duplicate_rule_id_fails(tmp_path):
    path = tmp_path / "rules.json"
    rule = {"rule_id": "x", "pattern": "a", "description": ""}
    path.write_text(json.dumps({"rules": [rule, rule]}), encoding="utf-8")
    with pytest.raises(ComplianceRulesError):
        load_stop_list(path)


@pytest.mark.parametrize(
    "text, rule_id",
    [
        ("Этот комплекс ВЫЛЕЧИТ суставы", "cure"),
        ("Омега-3 избавит вас от болей в суставах", "rid_of"),
        ("Магний поможет от бессонницы", "helps_against"),
        ("Хорошее средство от давления", "against_disease"),
        ("Витамин D гарантирует крепкий иммунитет", "guarantee_effect"),
        ("Эти капсулы заменяют лекарства", "replaces_medicine"),
        ("Цинк укрепит ваш иммунитет", "immunity_boost"),
        ("Коллаген лечит суставы", "treats"),
        ("Даём 100% результат", "hundred_percent"),
        ("Полное излечение за месяц", "cure"),
        ("Омега-3 рекомендуется для поддержки здоровья во время беременности", "health_support"),
        ("Этот массажёр снимет боль в суставах", "relieves"),
        ("Цинк поможет при простуде", "helps_with_condition"),
        ("Помогает при головной боли", "helps_with_condition"),
        ("Поможет при регулярных головных болях", "helps_with_condition"),
        ("Обладает лечебным эффектом", "healing_effect"),
        ("Курс оздоровит организм", "healing_effect"),
        ("Нормализует давление", "normalizes"),
        ("Омега-3 снижает холестерин", "normalizes"),
        ("Коллаген эффективен против артрита", "effective_against"),
        ("Принимайте для лечения гастрита", "for_treatment"),
    ],
)
def test_forbidden_phrases_trigger(stop_list, text, rule_id):
    matches = stop_list.check(text)
    assert rule_id in {m.rule_id for m in matches}
    assert all(m.fragment for m in matches)


def test_yo_normalization(stop_list):
    assert stop_list.check("Избавит от болёй")  # «ё» приводится к «е»


@pytest.mark.parametrize(
    "text",
    [
        "Не является лекарственным средством.",
        "Перед применением рекомендуется проконсультироваться с врачом.",
        "Если вы проходите лечение, проконсультируйтесь с врачом.",
        "На массажёры действует гарантия производителя 12 месяцев.",
        "Доставка до пункта выдачи стоит 290 ₽, отследить заказ можно в СДЭК.",
        "Защита от влаги, отличается от прошлой модели.",
        "Менеджер помогает при выборе размера.",
        "Помогает при выборе размера шейкера",
        "Принимать по 1 капсуле 2 раза в день во время еды.",
        "Доставка от 2 до 7 рабочих дней.",
        "При заболеваниях проконсультируйтесь с врачом.",
        "Уточню этот вопрос у специалиста и вернусь с ответом.",
    ],
)
def test_safe_texts_do_not_trigger(stop_list, text):
    assert stop_list.check(text) == []


def test_kb_texts_pass_stop_list(kb, stop_list):
    hits = [(entry_id, field, stop_list.check(text)) for entry_id, field, text in kb.texts()]
    assert [h for h in hits if h[2]] == []


def test_templates_pass_stop_list(stop_list):
    assert stop_list.check(SAFE_REPLY_TEMPLATE) == []
    assert stop_list.check(FAILURE_REPLY_TEMPLATE) == []
