import logging

import stripe
from fastapi import APIRouter, Header, HTTPException, Request

from app.core.config import settings
from app.core.database import get_supabase

router = APIRouter()
logger = logging.getLogger(__name__)


from datetime import datetime, timezone


def _attr(obj, key, default=None):
    """Acessa atributo ou chave de um objeto Stripe de forma segura."""
    try:
        return getattr(obj, key, default)
    except Exception:
        return default


def _period_end_iso(ts) -> str | None:
    if not ts:
        return None
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()


def _plan_from_subscription(sub) -> str:
    """Extrai 'monthly' ou 'annual' a partir do intervalo do preço."""
    try:
        interval = sub.items.data[0].price.recurring.interval
        return "annual" if interval == "year" else "monthly"
    except Exception:
        return "monthly"


def _handle_checkout_completed(event) -> None:
    """checkout.session.completed — vincula customer e ativa a assinatura."""
    session = event.data.object

    if _attr(session, "mode") != "subscription":
        return

    metadata = _attr(session, "metadata") or {}
    user_id = metadata.get("user_id") if hasattr(metadata, "get") else getattr(metadata, "user_id", None)
    if not user_id:
        logger.warning("checkout.session.completed sem user_id no metadata.")
        return

    stripe_customer_id = _attr(session, "customer")
    stripe_subscription_id = _attr(session, "subscription")
    if not stripe_subscription_id:
        return

    sub = stripe.Subscription.retrieve(stripe_subscription_id)
    plan = _plan_from_subscription(sub)
    period_end_iso = _period_end_iso(_attr(sub, "current_period_end"))

    supabase = get_supabase()
    supabase.table("subscriptions").upsert({
        "user_id": user_id,
        "stripe_customer_id": stripe_customer_id,
        "stripe_subscription_id": stripe_subscription_id,
        "status": "active",
        "plan": plan,
        "current_period_end": period_end_iso,
    }, on_conflict="user_id").execute()

    logger.info(f"Assinatura ativada para user_id {user_id} — plano {plan}")


def _handle_subscription_updated(event) -> None:
    """customer.subscription.updated — sincroniza status, plano e período."""
    sub = event.data.object
    stripe_subscription_id = _attr(sub, "id")
    if not stripe_subscription_id:
        return

    stripe_status = _attr(sub, "status") or ""
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
    period_end_iso = _period_end_iso(_attr(sub, "current_period_end"))

    supabase = get_supabase()
    supabase.table("subscriptions").update({
        "status": our_status,
        "plan": plan,
        "current_period_end": period_end_iso,
    }).eq("stripe_subscription_id", stripe_subscription_id).execute()

    logger.info(f"Assinatura {stripe_subscription_id} atualizada → {our_status}")


def _handle_subscription_deleted(event) -> None:
    """customer.subscription.deleted — marca como cancelada."""
    sub = event.data.object
    stripe_subscription_id = _attr(sub, "id")
    if not stripe_subscription_id:
        return

    supabase = get_supabase()
    supabase.table("subscriptions").update({
        "status": "canceled",
        "current_period_end": None,
    }).eq("stripe_subscription_id", stripe_subscription_id).execute()

    logger.info(f"Assinatura {stripe_subscription_id} cancelada.")


def _handle_invoice_payment_failed(event) -> None:
    """invoice.payment_failed — marca como inadimplente."""
    invoice = event.data.object
    stripe_subscription_id = _attr(invoice, "subscription")
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
    except stripe.error.SignatureVerificationError:
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
