import logging
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.database import get_supabase
from app.core.rate_limit import excedeu
from app.core.security import get_current_user, get_user_id
from app.models.schemas import UserProfileUpdate

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/me")
def get_profile(
    user_id: str = Depends(get_user_id),
    current_user: dict = Depends(get_current_user),
):
    """
    Retorna o perfil completo do usuário autenticado:
    dados de auth (e-mail) + preferências de notificação.
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

    return {
        "id": user_id,
        "email": current_user.get("email"),
        "profile": profile_result.data,
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
    # Cada chamada grava no banco; clicar em "conectar" repetidamente não
    # precisa de mais que alguns tokens por janela.
    if excedeu(f"telegram:{user_id}", 5, timedelta(minutes=10)):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Muitas tentativas. Aguarde alguns minutos para gerar um novo link.",
        )

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


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
def excluir_conta(user_id: str = Depends(get_user_id)):
    """
    Apaga a conta e todos os dados do usuário.

    Direito garantido pela LGPD, e por isso a ação é definitiva. Apagar em
    auth.users derruba junto perfil, ativos e logs de notificação, que têm
    on delete cascade. Os relatórios ficam: eles são de documentos públicos,
    não pertencem a ninguém e servem a quem mais acompanha o mesmo ativo.

    O frontend pede a senha antes de chegar aqui.
    """
    supabase = get_supabase()
    try:
        supabase.auth.admin.delete_user(user_id)
    except Exception as e:
        logger.error(f"Falha ao excluir conta {user_id}: {type(e).__name__}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Não foi possível excluir a conta agora. Tente novamente.",
        )

    logger.info(f"Conta excluída: {user_id}")
