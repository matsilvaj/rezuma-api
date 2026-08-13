from fastapi import APIRouter, Header, HTTPException, Request

from app.core.config import settings

router = APIRouter()


@router.post("/stripe")
async def stripe_webhook(request: Request, stripe_signature: str = Header(None)):
    """
    Recebe eventos do Stripe (pagamento confirmado, assinatura cancelada, etc.).
    Valida a assinatura do webhook antes de processar qualquer evento.
    """
    if not stripe_signature:
        raise HTTPException(status_code=400, detail="Assinatura do webhook ausente.")

    payload = await request.body()

    # TODO: validar assinatura com stripe.WebhookSignature e processar evento
    return {"received": True}


@router.post("/telegram")
async def telegram_webhook(request: Request):
    """
    Recebe updates do Telegram Bot API.
    Usado para processar comandos enviados pelos usuários no bot.
    """
    # TODO: processar updates do Telegram (comandos /start, /status, etc.)
    return {"ok": True}
