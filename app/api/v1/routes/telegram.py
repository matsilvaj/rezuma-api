import hmac
import logging

from fastapi import APIRouter, Header, HTTPException, Request, status

from app.core.config import settings
from app.core.database import get_supabase
from app.services.telegram import send_message

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str = Header(default=""),
):
    """
    Recebe updates do Telegram via webhook.
    Verifica o secret token para garantir que a requisição veio do Telegram.
    Processa o comando /start TOKEN para vincular a conta do usuário.
    """
    if not settings.TELEGRAM_WEBHOOK_SECRET:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Webhook não configurado.")
    if not hmac.compare_digest(x_telegram_bot_api_secret_token, settings.TELEGRAM_WEBHOOK_SECRET):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido.")

    body = await request.json()
    message = body.get("message", {})
    text = (message.get("text") or "").strip()
    chat_id = message.get("chat", {}).get("id")

    # Ignora mensagens que não sejam /start TOKEN
    if not text.startswith("/start ") or not chat_id:
        return {"ok": True}

    token = text.removeprefix("/start ").strip()
    if not token:
        return {"ok": True}

    supabase = get_supabase()

    # Busca usuário com esse token ainda válido
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()

    # maybe_single() retorna None (não APIResponse) quando nenhuma linha é encontrada
    row = (
        supabase.table("user_profiles")
        .select("id")
        .eq("telegram_link_token", token)
        .gt("telegram_link_token_expires_at", now)
        .maybe_single()
        .execute()
    )

    if not row:
        await send_message(chat_id, "❌ Link expirado ou inválido. Gere um novo link nas configurações do Rezuma.")
        return {"ok": True}

    user_id = row.data["id"] if hasattr(row, "data") else row["id"]

    # Salva o chat_id, ativa notificações e invalida o token
    supabase.table("user_profiles").update({
        "telegram_chat_id": str(chat_id),
        "notify_telegram": True,
        "telegram_link_token": None,
        "telegram_link_token_expires_at": None,
    }).eq("id", user_id).execute()

    await send_message(chat_id, "✅ Telegram vinculado com sucesso! Você receberá os resumos do Rezuma aqui.")
    logger.info(f"Telegram vinculado para user_id {user_id}")

    return {"ok": True}
