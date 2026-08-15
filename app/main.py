import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import router
from app.core.config import settings
from app.jobs.scheduler import seed_if_empty, start_scheduler, stop_scheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def _register_telegram_webhook() -> None:
    """
    Registra o webhook do Telegram na inicialização.
    Executado apenas em produção — requer BACKEND_URL e TELEGRAM_WEBHOOK_SECRET configurados.
    """
    if settings.APP_ENV != "production":
        return
    if not settings.BACKEND_URL or not settings.TELEGRAM_WEBHOOK_SECRET:
        logger.warning("Webhook do Telegram não registrado: BACKEND_URL ou TELEGRAM_WEBHOOK_SECRET ausente.")
        return

    webhook_url = f"{settings.BACKEND_URL}/api/v1/telegram/webhook"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/setWebhook",
            json={
                "url": webhook_url,
                "secret_token": settings.TELEGRAM_WEBHOOK_SECRET,
                "allowed_updates": ["message"],
            },
        )
    if resp.json().get("ok"):
        logger.info(f"Webhook do Telegram registrado: {webhook_url}")
    else:
        logger.error(f"Falha ao registrar webhook do Telegram: {resp.text}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gerencia o ciclo de vida da aplicação: inicia scheduler, seed e webhook."""
    start_scheduler()
    await seed_if_empty()
    await _register_telegram_webhook()
    yield
    stop_scheduler()


app = FastAPI(
    title="Rezuma API",
    description="Backend do Rezuma — resumos de relatórios de ações e FIIs.",
    version="1.0.0",
    lifespan=lifespan,
    # Desabilita docs automáticas em produção
    docs_url="/docs" if settings.APP_ENV != "production" else None,
    redoc_url="/redoc" if settings.APP_ENV != "production" else None,
)

# Permite requisições apenas do frontend cadastrado
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")


@app.get("/health", tags=["Health"])
def health_check():
    """Endpoint de health check usado pelo Railway para monitorar o serviço."""
    return {"status": "ok"}
