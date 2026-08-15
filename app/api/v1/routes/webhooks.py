import logging

import stripe
from fastapi import APIRouter, Header, HTTPException, Request

from app.core.config import settings

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/stripe")
async def stripe_webhook(request: Request, stripe_signature: str = Header(None, alias="stripe-signature")):
    """
    Recebe eventos do Stripe. Valida a assinatura antes de processar qualquer evento.
    """
    if not stripe_signature:
        raise HTTPException(status_code=400, detail="Assinatura do webhook ausente.")

    payload = await request.body()

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=stripe_signature,
            secret=settings.STRIPE_WEBHOOK_SECRET,
        )
    except stripe.errors.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Assinatura inválida.")
    except Exception:
        raise HTTPException(status_code=400, detail="Payload inválido.")

    event_type = event["type"]
    logger.info(f"Stripe event recebido: {event_type}")

    # TODO: implementar handlers por event_type (ex: checkout.session.completed)

    return {"received": True}
