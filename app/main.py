"""FastAPI-приложение. Запуск: uvicorn app.main:create_app --factory"""

import json
import logging
import secrets
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.adapter import DialogAdapter
from app.amo_webhook import parse_amo_webhook
from app.compliance import load_stop_list
from app.config import Settings
from app.crm import AmoCrmClient, CrmClient, MockCrmClient
from app.dialogs import DialogStore
from app.kb import load_knowledge_base
from app.llm import LLMClient, OpenAILLMClient
from app.schemas import ReplyRequest, ReplyResponse
from app.service import ReplyService

MOCK_PAGE = Path(__file__).resolve().parent / "static" / "mock.html"


def create_app(
    settings: Settings | None = None,
    llm_client: LLMClient | None = None,
    crm_client: CrmClient | None = None,
) -> FastAPI:
    logging.basicConfig(level=logging.INFO)
    settings = settings or Settings()
    # Ошибка в данных останавливает запуск: KnowledgeBaseError / ComplianceRulesError.
    kb = load_knowledge_base(settings.kb_path)
    stop_list = load_stop_list(settings.compliance_rules_path)
    service = ReplyService(
        kb=kb,
        stop_list=stop_list,
        llm=llm_client or OpenAILLMClient(settings),
        history_limit=settings.history_limit,
    )
    crm = crm_client or _make_crm_client(settings)
    dialogs = DialogStore()
    adapter = DialogAdapter(service, dialogs, crm)
    webhook_secret = settings.webhook_secret.get_secret_value() if settings.webhook_secret else ""

    app = FastAPI(title="core-reply-service")
    app.state.service = service
    app.state.dialogs = dialogs
    app.state.crm = crm

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "kb_version": kb.version}

    @app.post("/v1/reply", response_model=ReplyResponse)
    def reply(request: ReplyRequest) -> ReplyResponse:
        return service.reply(request)

    @app.post("/webhooks/amo")
    async def amo_webhook(request: Request, background: BackgroundTasks, token: str = "") -> dict:
        # Вебхуки аккаунта amoCRM не подписываются, поэтому секрет передаётся в адресе.
        if webhook_secret and not secrets.compare_digest(token.encode(), webhook_secret.encode()):
            raise HTTPException(status_code=401, detail="invalid token")
        events = parse_amo_webhook(await request.body())
        jobs = adapter.accept(events)
        # amoCRM ждёт быстрый ответ, а модель отвечает секунды: генерация идёт после ответа.
        for event, history in jobs:
            background.add_task(adapter.generate, event, history)
        return {"accepted": len(events), "queued": len(jobs)}

    if settings.crm_mode == "mock" and isinstance(crm, MockCrmClient):
        _add_mock_routes(app, dialogs, crm, webhook_secret)

    return app


def _make_crm_client(settings: Settings) -> CrmClient:
    if settings.crm_mode == "amo":
        # Наличие настроек проверил валидатор Settings.
        return AmoCrmClient(settings.amo_subdomain, settings.amo_access_token.get_secret_value())
    return MockCrmClient()


def _add_mock_routes(app: FastAPI, dialogs: DialogStore, crm: MockCrmClient, webhook_secret: str) -> None:
    # Страница локальная, поэтому токен вебхука подставляется в неё, чтобы mock работал и с секретом.
    token_js = json.dumps(webhook_secret).replace("<", "\\u003c")
    page = MOCK_PAGE.read_text(encoding="utf-8").replace("__WEBHOOK_TOKEN__", token_js)

    @app.get("/mock", response_class=HTMLResponse)
    def mock_page() -> str:
        return page

    @app.get("/mock/leads/{lead_id}")
    def mock_lead(lead_id: int) -> dict:
        return {
            "lead_id": lead_id,
            "messages": [m.model_dump() for m in dialogs.messages(lead_id)],
            "notes": [
                {"text": n.text, "created_at": n.created_at.isoformat()} for n in crm.notes(lead_id)
            ],
        }
