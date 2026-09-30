import pytest
from fastapi.testclient import TestClient

from app.compliance import load_stop_list
from app.config import Settings
from app.kb import load_knowledge_base
from app.llm import build_llm_output_model
from app.main import create_app
from app.service import ReplyService
from tests.fakes import FakeLLMClient


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None)


@pytest.fixture
def kb(settings):
    return load_knowledge_base(settings.kb_path)


@pytest.fixture
def stop_list(settings):
    return load_stop_list(settings.compliance_rules_path)


@pytest.fixture
def output_model(kb):
    return build_llm_output_model(kb)


@pytest.fixture
def make_service(kb, stop_list):
    def _make(llm: FakeLLMClient, history_limit: int = 10) -> ReplyService:
        return ReplyService(kb=kb, stop_list=stop_list, llm=llm, history_limit=history_limit)

    return _make


@pytest.fixture
def make_client(settings):
    def _make(llm: FakeLLMClient) -> TestClient:
        return TestClient(create_app(settings=settings, llm_client=llm))

    return _make
