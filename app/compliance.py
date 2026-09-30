"""Стоп-лист медицинских обещаний и безопасные шаблоны ответа."""

import json
import re
from dataclasses import dataclass
from pathlib import Path

SAFE_REPLY_TEMPLATE = (
    "Спасибо за вопрос! Хочу ответить вам точно, поэтому уточню детали у специалиста "
    "и вернусь с ответом."
)
FAILURE_REPLY_TEMPLATE = "Спасибо за сообщение! Уточню детали и вернусь к вам с ответом."


class ComplianceRulesError(Exception):
    pass


@dataclass(frozen=True)
class Rule:
    rule_id: str
    pattern: re.Pattern[str]
    description: str


@dataclass(frozen=True)
class RuleMatch:
    rule_id: str
    fragment: str


def normalize(text: str) -> str:
    return text.lower().replace("ё", "е")


class StopList:
    def __init__(self, rules: list[Rule]):
        self.rules = rules

    def check(self, text: str) -> list[RuleMatch]:
        normalized = normalize(text)
        return [
            RuleMatch(rule.rule_id, match.group(0))
            for rule in self.rules
            for match in rule.pattern.finditer(normalized)
        ]


def load_stop_list(path: Path) -> StopList:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ComplianceRulesError(f"Не удалось прочитать стоп-лист {path}: {exc}") from exc

    rules = []
    seen: set[str] = set()
    for item in raw.get("rules", []):
        rule_id = item.get("rule_id")
        if not rule_id or rule_id in seen:
            raise ComplianceRulesError(f"Пустой или повторяющийся rule_id: {rule_id!r}")
        seen.add(rule_id)
        try:
            pattern = re.compile(item["pattern"])
        except (KeyError, re.error) as exc:
            raise ComplianceRulesError(f"Правило {rule_id}: некорректный pattern: {exc}") from exc
        rules.append(Rule(rule_id, pattern, item.get("description", "")))
    if not rules:
        raise ComplianceRulesError("Стоп-лист пуст")
    return StopList(rules)
