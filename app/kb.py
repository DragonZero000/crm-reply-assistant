"""База знаний: модели записей, загрузка с проверкой целостности, текст для промпта."""

import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError


class KnowledgeBaseError(Exception):
    pass


class FaqEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    type: Literal["faq"]
    title: str = Field(min_length=1)
    content: str = Field(min_length=1)


class ProductEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    type: Literal["product"]
    title: str = Field(min_length=1)
    content: str = Field(min_length=1)
    price: int = Field(gt=0)
    pitch: str = Field(min_length=1)
    related_ids: list[str]
    contraindications: str | None = None


Entry = Annotated[FaqEntry | ProductEntry, Field(discriminator="type")]
_entry_adapter: TypeAdapter[FaqEntry | ProductEntry] = TypeAdapter(Entry)


class KnowledgeBase(BaseModel):
    version: str
    entries: list[FaqEntry | ProductEntry]

    @property
    def by_id(self) -> dict[str, FaqEntry | ProductEntry]:
        return {entry.id: entry for entry in self.entries}

    @property
    def products(self) -> dict[str, ProductEntry]:
        return {e.id: e for e in self.entries if isinstance(e, ProductEntry)}

    def entry_ids(self) -> list[str]:
        return sorted(entry.id for entry in self.entries)

    def product_ids(self) -> list[str]:
        return sorted(self.products)

    def texts(self) -> list[tuple[str, str, str]]:
        """Все тексты базы как (id записи, поле, текст) — для проверки стоп-листом."""
        result = []
        for entry in self.entries:
            result.append((entry.id, "title", entry.title))
            result.append((entry.id, "content", entry.content))
            if isinstance(entry, ProductEntry):
                result.append((entry.id, "pitch", entry.pitch))
                if entry.contraindications:
                    result.append((entry.id, "contraindications", entry.contraindications))
        return result


def parse_knowledge_base(raw: dict) -> KnowledgeBase:
    if not isinstance(raw, dict) or "version" not in raw or not isinstance(raw.get("entries"), list):
        raise KnowledgeBaseError("База знаний должна содержать поля 'version' и 'entries' (список)")

    entries = []
    for index, raw_entry in enumerate(raw["entries"]):
        entry_id = raw_entry.get("id", f"#{index}") if isinstance(raw_entry, dict) else f"#{index}"
        try:
            entries.append(_entry_adapter.validate_python(raw_entry))
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(str(p) for p in err['loc'][1:]) or 'запись'}: {err['msg']}"
                for err in exc.errors()
            )
            raise KnowledgeBaseError(f"Запись {entry_id}: {problems}") from exc

    seen: set[str] = set()
    for entry in entries:
        if entry.id in seen:
            raise KnowledgeBaseError(f"Повторяющийся id записи: {entry.id}")
        seen.add(entry.id)

    product_ids = {e.id for e in entries if isinstance(e, ProductEntry)}
    for entry in entries:
        if not isinstance(entry, ProductEntry):
            continue
        for related_id in entry.related_ids:
            if related_id == entry.id:
                raise KnowledgeBaseError(f"Товар {entry.id} ссылается сам на себя в related_ids")
            if related_id not in product_ids:
                raise KnowledgeBaseError(
                    f"Товар {entry.id}: в related_ids указан {related_id}, такого товара нет в базе"
                )

    return KnowledgeBase(version=str(raw["version"]), entries=entries)


def load_knowledge_base(path: Path) -> KnowledgeBase:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise KnowledgeBaseError(f"Не удалось прочитать базу знаний {path}: {exc}") from exc
    return parse_knowledge_base(raw)


def render_knowledge_base(kb: KnowledgeBase) -> str:
    """Детерминированный текст базы для системного промпта: FAQ, затем товары, внутри — по id."""
    ordered = sorted(kb.entries, key=lambda e: (e.type, e.id))
    products = kb.products
    blocks = []
    for entry in ordered:
        lines = [f'<entry id="{entry.id}" type="{entry.type}">', f"Название: {entry.title}"]
        if isinstance(entry, ProductEntry):
            lines.append(f"Цена: {entry.price} ₽")
        lines.append(entry.content)
        if isinstance(entry, ProductEntry):
            if entry.contraindications:
                lines.append(f"Противопоказания: {entry.contraindications}")
            if entry.related_ids:
                related = ", ".join(f"{rid} ({products[rid].title})" for rid in entry.related_ids)
                lines.append(f"Можно предложить вместе с ним: {related}")
            else:
                lines.append("Можно предложить вместе с ним: нет")
        lines.append("</entry>")
        blocks.append("\n".join(lines))
    return f'<knowledge_base version="{kb.version}">\n' + "\n\n".join(blocks) + "\n</knowledge_base>"
