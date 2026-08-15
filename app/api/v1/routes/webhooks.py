import logging

import stripe
from fastapi import APIRouter, Header, HTTPException, Request

from app.core.config import settings
from app.core.database import get_supabase

router = APIRouter()
logger = logging.getLogger(__name__)


def _plan_from_subscription(sub: stripe.Subscription) -> str:
    """Extrai 'monthly' ou 'annual' a partir do intervalo do preço."""
    try:
        interval = sub["items"]["data"][0]["price"]["recurring"]["interval"]
        return "annual" if interval == "year" else "monthly"
    except (KeyError, IndexError):
        return "monthly"


def _handle_checkout_completed(event: dict) -> None:
    """checkout.session.completed — vincula customer e ativa a assinatura."""
    session = event["data"]["object"]
    if session.get("mode") != "subscription":
        return

    user_id = (session.get("metadata") or {}).get("user_id")
    if not user_id:
        logger.warning("checkout.session.completed sem user_id no metadata.")
        return

    stripe_customer_id = session.get("customer")
    stripe_subscription_id = session.get("subscription")

    if not stripe_subscription_id:
        return

    sub = stripe.Subscription.retrieve(stripe_subscription_id)
    plan = _plan_from_subscription(sub)
    current_period_end = sub.get("current_period_end")
    period_end_iso = (
        stripe.util.convert_to_dict({"t": current_period_end})["t"]
        if current_period_end
        else None
    )

    # Converte timestamp Unix para ISO 8601
    from datetime import datetime, timezone
    period_end_iso = (
        datetime.fromtimestamp(current_period_end, tz=timezone.utc).isoformat()
        if current_period_end
        else None
    )

    supabase = get_supabase()
    supabase.table("subscriptions").update({
        "stripe_customer_id": stripe_customer_id,
        "stripe_subscription_id": stripe_subscription_id,
        "status": "active",
        "plan": plan,
        "current_period_end": period_end_iso,
    }).eq("user_id", user_id).execute()

    logger.info(f"Assinatura ativada para user_id {user_id} — plano {plan}")


def _handle_subscription_updated(event: dict) -> None:
    """customer.subscription.updated — sincroniza status, plano e período."""
    sub = event["data"]["object"]
    stripe_subscription_id = sub.get("id")
    if not stripe_subscription_id:
        return

    stripe_status = sub.get("status", "")
    status_map = {
        "active": "active",
        "trialing": "trialing",
        "past_due": "past_due",
        "canceled": "canceled",
        "unpaid": "past_due",
        "incomplete": "past_due",
        "incomplete_expired": "canceled",
        "paused": "past_due",
    }
    our_status = status_map.get(stripe_status, "past_due")
    plan = _plan_from_subscription(sub)

    from datetime import datetime, timezone
    current_period_end = sub.get("current_period_end")
    period_end_iso = (
        datetime.fromtimestamp(current_period_end, tz=timezone.utc).isoformat()
        if current_period_end
        else None
    )

    supabase = get_supabase()
    supabase.table("subscriptions").update({
        "status": our_status,
        "plan": plan,
        "current_period_end": period_end_iso,
    }).eq("stripe_subscription_id", stripe_subscription_id).execute()

    logger.info(f"Assinatura {stripe_subscription_id} atualizada → {our_status}")


def _handle_subscription_deleted(event: dict) -> None:
    """customer.subscription.deleted — marca como cancelada."""
    sub = event["data"]["object"]
    stripe_subscription_id = sub.get("id")
    if not stripe_subscription_id:
        return

    supabase = get_supabase()
    supabase.table("subscriptions").update({
        "status": "canceled",
        "current_period_end": None,
    }).eq("stripe_subscription_id", stripe_subscription_id).execute()

    logger.info(f"Assinatura {stripe_subscription_id} cancelada.")


def _handle_invoice_payment_failed(event: dict) -> None:
    """invoice.payment_failed — marca como inadimplente."""
    invoice = event["data"]["object"]
    stripe_subscription_id = invoice.get("subscription")
    if not stripe_subscription_id:
        return

    supabase = get_supabase()
    supabase.table("subscriptions").update({
        "status": "past_due",
    }).eq("stripe_subscription_id", stripe_subscription_id).execute()

    logger.warning(f"Pagamento falhou para assinatura {stripe_subscription_id} → past_due")


_HANDLERS = {
    "checkout.session.completed": _handle_checkout_completed,
    "customer.subscription.updated": _handle_subscription_updated,
    "customer.subscription.deleted": _handle_subscription_deleted,
    "invoice.payment_failed": _handle_invoice_payment_failed,
}


@router.post("/stripe")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None, alias="stripe-signature"),
):
    """Recebe eventos do Stripe. Valida a assinatura antes de processar."""
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

    handler = _HANDLERS.get(event_type)
    if handler:
        try:
            handler(event)
        except Exception as e:
            logger.error(f"Erro ao processar evento {event_type}: {e}")

    return {"received": True}
