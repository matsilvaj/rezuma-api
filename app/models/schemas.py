from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class BaseResponse(BaseModel):
    """Schema base para respostas padronizadas da API."""
    message: str
    success: bool = True


# ---------------------------------------------------------------------------
# Usuário
# ---------------------------------------------------------------------------

class UserProfile(BaseModel):
    """Dados públicos do perfil do usuário."""
    id: str
    email: EmailStr
    full_name: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    notify_email: bool = True
    notify_telegram: bool = False
    created_at: datetime


class UserProfileUpdate(BaseModel):
    """Campos que o usuário pode atualizar no próprio perfil."""
    full_name: Optional[str] = None
    notify_email: Optional[bool] = None
    notify_telegram: Optional[bool] = None
    # telegram_chat_id é escrito apenas pelo webhook do bot — não exposto aqui


# ---------------------------------------------------------------------------
# Ativos
# ---------------------------------------------------------------------------

class AssetCreate(BaseModel):
    """Payload para adicionar um ativo à carteira."""
    ticker: str

    def model_post_init(self, __context) -> None:
        """Normaliza o ticker para maiúsculo antes de qualquer validação."""
        self.ticker = self.ticker.strip().upper()


class Asset(BaseModel):
    """Representação de um ativo cadastrado pelo usuário."""
    id: str
    user_id: str
    ticker: str
    created_at: datetime


# ---------------------------------------------------------------------------
# Relatórios
# ---------------------------------------------------------------------------

class Report(BaseModel):
    """Resumo gerado para um relatório de ativo."""
    id: str
    ticker: str
    title: str
    summary: str
    source_url: str
    published_at: datetime
    created_at: datetime
