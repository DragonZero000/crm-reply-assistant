import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.crm import CrmError, MockCrmClient
from app.llm import CallContext
from app.main import create_app
from tests.fakes import FakeLLMClient, amo_body, amo_message, llm_output

FORM = {"Content-Type": "application/x-www-form-urlencoded"}


def make_app(llm: FakeLLMClient, crm=None, **settings):
    return create_app(settings=Settings(_env_file=None, **settings), llm_client=llm, crm_client=crm)


def post(client: TestClient, *messages: dict, token: str | None = None):
    url = "/webhooks/amo" + (f"?token={token}" if token is not None else "")
    return client.post(url, content=amo_body(*messages), headers=FORM)


def upsell_output() -> dict:
    return llm_output(
        client_reply="В 1 капсуле 1000 мг рыбьего жира.",
        used_kb_ids=["omega3_1000"],
        upsell=[{"product_id": "vit_d3_2000", "why_now": "Клиент берёт курс на месяц."}],
    )


def test_client_message_creates_note():
    llm = FakeLLMClient(llm_output())
    app = make_app(llm)
    response = post(TestClient(app), amo_message("m1", "Сколько стоит доставка?"))
    assert response.status_code == 200
    assert response.json() == {"accepted": 1, "queued": 1}
    [note] = app.state.crm.notes(555)
    assert note.text.startswith("Черновик ответа (не отправлен клиенту)\nДоставка до пункта выдачи стоит 290 ₽.")


def test_manager_message_only_history():
    llm = FakeLLMClient(llm_output())
    app = make_app(llm)
    response = post(TestClient(app), amo_message("m1", "Могу добавить витамин D3", type="outgoing"))
    assert response.json() == {"accepted": 1, "queued": 0}
    assert llm.calls == []
    assert app.state.crm.notes(555) == []
    assert [m.role for m in app.state.dialogs.messages(555)] == ["manager"]


def test_history_passed_to_model():
    llm = FakeLLMClient(llm_output())
    client = TestClient(make_app(llm))
    post(client, amo_message("m1", "Хочу Омега-3"), amo_message("m2", "Она в наличии", type="outgoing"))
    post(client, amo_message("m3", "А доставка в Казань?"))
    sent = llm.calls[-1]["user_message"]
    assert "[клиент]: Хочу Омега-3\n[менеджер]: Она в наличии\n</history>" in sent
    assert "<new_message>\nА доставка в Казань?" in sent


def test_call_context_passed_to_model():
    llm = FakeLLMClient(llm_output())
    post(TestClient(make_app(llm)), amo_message("msg-1", "Сколько стоит доставка?"))
    assert llm.calls[-1]["context"] == CallContext(lead_id=555, message_id="msg-1")


def test_leads_do_not_mix():
    llm = FakeLLMClient(llm_output())
    client = TestClient(make_app(llm))
    post(client, amo_message("m1", "Сообщение по 555"))
    post(client, amo_message("m2", "Сообщение по 777", lead_id=777))
    assert "Сообщение по 555" not in llm.calls[-1]["user_message"]


def test_redelivery_does_not_duplicate_note():
    llm = FakeLLMClient(llm_output())
    app = make_app(llm)
    client = TestClient(app)
    post(client, amo_message("m1", "Сколько стоит доставка?"))
    response = post(client, amo_message("m1", "Сколько стоит доставка?"))
    assert response.json() == {"accepted": 1, "queued": 0}
    assert len(app.state.crm.notes(555)) == 1
    assert len(llm.calls) == 1


def test_second_note_does_not_repeat_upsell():
    llm = FakeLLMClient(upsell_output())
    app = make_app(llm)
    client = TestClient(app)
    post(client, amo_message("m1", "Что в составе омеги?"))
    post(client, amo_message("m2", "А как принимать?"))
    first, second = [n.text for n in app.state.crm.notes(555)]
    assert "Клиент берёт курс на месяц." in first
    assert "Клиент берёт курс на месяц." not in second and "Можно предложить" not in second


def test_upsell_of_other_lead_not_excluded():
    llm = FakeLLMClient(upsell_output())
    app = make_app(llm)
    client = TestClient(app)
    post(client, amo_message("m1", "Что в составе омеги?"))
    post(client, amo_message("m2", "Что в составе омеги?", lead_id=777))
    assert "Можно предложить" in app.state.crm.notes(777)[0].text


def test_not_in_kb_note():
    llm = FakeLLMClient(llm_output(
        client_reply="Уточню этот вопрос у специалиста и вернусь с ответом.",
        used_kb_ids=[],
        needs_human=True,
        reason="no_kb_answer",
    ))
    app = make_app(llm)
    post(TestClient(app), amo_message("m1", "Можно самовывозом?"))
    assert "Нужен менеджер: ответа нет в базе знаний." in app.state.crm.notes(555)[0].text


def test_llm_failure_still_creates_note():
    from app.llm import LLMFailure

    app = make_app(FakeLLMClient(error=LLMFailure("api_error")))
    post(TestClient(app), amo_message("m1", "Привет"))
    assert "Черновик не сформирован" in app.state.crm.notes(555)[0].text


class FailingCrm(MockCrmClient):
    def __init__(self):
        super().__init__()
        self.fail = True

    def add_note(self, lead_id: int, text: str) -> None:
        if self.fail:
            self.fail = False
            raise CrmError("amoCRM ответила 500")
        super().add_note(lead_id, text)


def test_crm_error_logged_and_next_webhook_works(caplog):
    llm = FakeLLMClient(upsell_output())
    crm = FailingCrm()
    client = TestClient(make_app(llm, crm=crm))
    assert post(client, amo_message("m1", "Что в составе омеги?")).status_code == 200
    assert "Не удалось записать примечание к сделке 555" in caplog.text
    post(client, amo_message("m2", "Что в составе омеги?"))
    # Первое примечание не записано — допродажа из него не считается выданной.
    [note] = crm.notes(555)
    assert "Можно предложить" in note.text


def test_invalid_token_rejected():
    llm = FakeLLMClient(llm_output())
    app = make_app(llm, webhook_secret="s3cret")
    client = TestClient(app)
    assert post(client, amo_message("m1", "Привет"), token="wrong").status_code == 401
    assert post(client, amo_message("m1", "Привет")).status_code == 401
    assert app.state.dialogs.messages(555) == []
    assert llm.calls == []


def test_valid_token_accepted():
    app = make_app(FakeLLMClient(llm_output()), webhook_secret="s3cret")
    assert post(TestClient(app), amo_message("m1", "Привет"), token="s3cret").status_code == 200


def test_no_secret_accepts_without_token():
    app = make_app(FakeLLMClient(llm_output()))
    assert post(TestClient(app), amo_message("m1", "Привет")).status_code == 200


def test_skipped_messages_do_not_fail_webhook():
    app = make_app(FakeLLMClient(llm_output()))
    response = post(TestClient(app), amo_message("m1", "Без сделки", lead_id=None), amo_message("m2", " "))
    assert response.status_code == 200
    assert response.json() == {"accepted": 0, "queued": 0}


def test_amo_mode_uses_amo_client():
    from app.crm import AmoCrmClient

    app = make_app(
        FakeLLMClient(llm_output()),
        crm_mode="amo", amo_subdomain="demo", amo_access_token="tkn", webhook_secret="s3cret",
    )
    assert isinstance(app.state.crm, AmoCrmClient)


# --- mock-режим ---


def test_mock_lead_endpoint():
    app = make_app(FakeLLMClient(llm_output()))
    client = TestClient(app)
    post(client, amo_message("m1", "Сколько стоит доставка?"))
    body = client.get("/mock/leads/555").json()
    assert body["messages"] == [{"role": "client", "text": "Сколько стоит доставка?"}]
    assert len(body["notes"]) == 1
    assert body["notes"][0]["text"].startswith("Черновик ответа")
    assert body["notes"][0]["created_at"]


def test_mock_unknown_lead_empty():
    client = TestClient(make_app(FakeLLMClient(llm_output())))
    response = client.get("/mock/leads/999")
    assert response.status_code == 200
    assert response.json() == {"lead_id": 999, "messages": [], "notes": []}


def test_mock_page():
    response = TestClient(make_app(FakeLLMClient(llm_output()))).get("/mock")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "const WEBHOOK_TOKEN = \"\";" in response.text
    assert "/webhooks/amo" in response.text


def test_mock_page_embeds_secret():
    response = TestClient(make_app(FakeLLMClient(llm_output()), webhook_secret="s3cret")).get("/mock")
    assert "const WEBHOOK_TOKEN = \"s3cret\";" in response.text


@pytest.mark.parametrize("path", ["/mock", "/mock/leads/555"])
def test_mock_routes_absent_in_amo_mode(path):
    app = make_app(
        FakeLLMClient(llm_output()),
        crm_mode="amo", amo_subdomain="demo", amo_access_token="tkn", webhook_secret="s3cret",
    )
    assert TestClient(app).get(path).status_code == 404
