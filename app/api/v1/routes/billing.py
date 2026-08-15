import logging

import stripe
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.core.config import settings
from app.core.database import get_supabase
from app.core.security import get_user_id

router = APIRouter()
logger = logging.getLogger(__name__)

_VALID_PLANS = {"monthly": "STRIPE_PRICE_MONTHLY", "annual": "STRIPE_PRICE_ANNUAL"}


class CheckoutRequest(BaseModel):
    plan: str  # "monthly" | "annual"


@router.post("/checkout")
def create_checkout_session(
    body: CheckoutRequest,
    user_id: str = Depends(get_user_id),
):
    """
    Cria uma Checkout Session do Stripe para o plano solicitado.
    Retorna a URL para redirecionar o usuário.
    """
    if body.plan not in _VALID_PLANS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Plano inválido.")

    price_id = getattr(settings, _VALID_PLANS[body.plan], "")
    if not price_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Plano não configurado.",
        )

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            metadata={"user_id": user_id},
            client_reference_id=user_id,
            success_url=f"{settings.FRONTEND_URL}/dashboard?checkout=success",
            cancel_url=f"{settings.FRONTEND_URL}/settings?checkout=canceled",
        )
    except stripe.StripeError as e:
        logger.error(f"Erro ao criar checkout session para {user_id}: {e}")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Erro ao iniciar pagamento.")

    return {"url": session.url}


@router.post("/portal")
def create_portal_session(user_id: str = Depends(get_user_id)):
    """
    Cria uma sessão do Customer Portal do Stripe para o usuário gerenciar a assinatura.
    Requer que o usuário já tenha um stripe_customer_id vinculado.
    """
    supabase = get_supabase()
    sub = (
        supabase.table("subscriptions")
        .select("stripe_customer_id")
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    customer_id = (sub.data or {}).get("stripe_customer_id") if sub else None

    if not customer_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nenhuma assinatura ativa encontrada.",
        )

    try:
        session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=f"{settings.FRONTEND_URL}/settings",
        )
    except stripe.StripeError as e:
        logger.error(f"Erro ao criar portal session para {user_id}: {e}")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Erro ao abrir portal.")

    return {"url": session.url}
