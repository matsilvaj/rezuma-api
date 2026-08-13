import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.database import get_supabase
from app.core.security import get_current_user, get_user_id
from app.models.schemas import UserProfileUpdate

router = APIRouter()


@router.get("/me")
def get_profile(
    user_id: str = Depends(get_user_id),
    current_user: dict = Depends(get_current_user),
):
    """
    Retorna o perfil completo do usuário autenticado:
    dados de auth (e-mail) + preferências de notificação + status da assinatura.
    """
    supabase = get_supabase()

    # Busca perfil e preferências de notificação
    profile_result = (
        supabase.table("user_profiles")
        .select("full_name, notify_email, notify_telegram, telegram_chat_id, created_at")
        .eq("id", user_id)
        .single()
        .execute()
    )

    # Busca status da assinatura — pode não existir para usuários muito novos
    subscription_result = (
        supabase.table("subscriptions")
        .select("status, plan, trial_ends_at, current_period_end")
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )

    return {
        "id": user_id,
        "email": current_user.get("email"),
        "profile": profile_result.data,
        "subscription": subscription_result.data,
    }


@router.patch("/me")
def update_profile(body: UserProfileUpdate, user_id: str = Depends(get_user_id)):
    """
    Atualiza as preferências do usuário autenticado.
    Apenas os campos enviados no body são atualizados.
    """
    supabase = get_supabase()

    # Monta apenas os campos que foram enviados (ignora None)
    updates = body.model_dump(exclude_none=True)

    if not updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nenhum campo para atualizar.",
        )

    supabase.table("user_profiles").update(updates).eq("id", user_id).execute()

    return {"message": "Perfil atualizado com sucesso."}


@router.post("/me/telegram/link")
def generate_telegram_link_token(user_id: str = Depends(get_user_id)):
    """
    Gera um token temporário (15 min) para o usuário vincular o Telegram.
    O token é enviado via deep link para o bot: t.me/BotName?start=TOKEN.
    """
    token = secrets.token_urlsafe(32)
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()

    supabase = get_supabase()
    supabase.table("user_profiles").update({
        "telegram_link_token": token,
        "telegram_link_token_expires_at": expires_at,
    }).eq("id", user_id).execute()

    return {"token": token}


@router.delete("/me/telegram", status_code=status.HTTP_204_NO_CONTENT)
def disconnect_telegram(user_id: str = Depends(get_user_id)):
    """
    Remove a vinculação do Telegram do usuário e desativa as notificações via Telegram.
    """
    supabase = get_supabase()
    supabase.table("user_profiles").update({
        "telegram_chat_id": None,
        "notify_telegram": False,
        "telegram_link_token": None,
        "telegram_link_token_expires_at": None,
    }).eq("id", user_id).execute()
