import copy
import json

import pytest

from app.kb import (
    FaqEntry,
    KnowledgeBaseError,
    ProductEntry,
    load_knowledge_base,
    parse_knowledge_base,
    render_knowledge_base,
)
from app.llm import build_llm_output_model


@pytest.fixture
def raw_kb(settings):
    return json.loads(settings.kb_path.read_text(encoding="utf-8"))


def test_entry_models():
    ProductEntry(
        id="p", type="product", title="T", content="C", price=100, pitch="P", related_ids=[]
    )
    FaqEntry(id="f", type="faq", title="T", content="C")
    with pytest.raises(Exception):
        ProductEntry(id="p", type="product", title="T", content="C", price=100, related_ids=[])


def test_real_kb_loads(kb):
    faq = [e for e in kb.entries if e.type == "faq"]
    products = [e for e in kb.entries if e.type == "product"]
    assert len(faq) == 5
    assert len(products) == 9
    assert kb.version
    assert any(p.contraindications for p in products)
    assert any(not p.related_ids for p in products)


def test_product_without_pitch_fails(raw_kb):
    raw = copy.deepcopy(raw_kb)
    product = next(e for e in raw["entries"] if e["type"] == "product")
    del product["pitch"]
    with pytest.raises(KnowledgeBaseError) as exc:
        parse_knowledge_base(raw)
    assert product["id"] in str(exc.value)
    assert "pitch" in str(exc.value)


def test_duplicate_id_fails(raw_kb):
    raw = copy.deepcopy(raw_kb)
    raw["entries"].append(copy.deepcopy(raw["entries"][0]))
    with pytest.raises(KnowledgeBaseError, match=raw["entries"][0]["id"]):
        parse_knowledge_base(raw)


def test_unknown_related_id_fails(raw_kb):
    raw = copy.deepcopy(raw_kb)
    omega = next(e for e in raw["entries"] if e["id"] == "omega3_1000")
    omega["related_ids"].append("unknown_product")
    with pytest.raises(KnowledgeBaseError) as exc:
        parse_knowledge_base(raw)
    assert "omega3_1000" in str(exc.value) and "unknown_product" in str(exc.value)


def test_unreadable_file(tmp_path):
    path = tmp_path / "kb.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(KnowledgeBaseError):
        load_knowledge_base(path)


def test_render_is_deterministic(settings):
    first = render_knowledge_base(load_knowledge_base(settings.kb_path))
    second = render_knowledge_base(load_knowledge_base(settings.kb_path))
    assert first == second
    assert first.encode() == second.encode()


def test_render_contains_all_entries(kb):
    text = render_knowledge_base(kb)
    for entry in kb.entries:
        assert f'id="{entry.id}"' in text


def test_enums_match_kb(kb):
    schema = build_llm_output_model(kb).model_json_schema()
    kb_enum = schema["properties"]["used_kb_ids"]["items"]["enum"]
    upsell_def = next(d for name, d in schema["$defs"].items() if name == "LLMUpsell")
    product_enum = upsell_def["properties"]["product_id"]["enum"]
    assert sorted(kb_enum) == sorted(e.id for e in kb.entries)
    assert sorted(product_enum) == sorted(kb.products)
