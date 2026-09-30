from tests.fakes import FakeLLMClient


def test_health(make_client, kb):
    response = make_client(FakeLLMClient()).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "kb_version": kb.version}
