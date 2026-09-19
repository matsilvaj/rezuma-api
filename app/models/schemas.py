import re
from datetime import datetime
from typing import Annotated, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator


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
    full_name: Optional[Annotated[str, Field(min_length=2, max_length=120)]] = None
    notify_email: Optional[bool] = None
    notify_telegram: Optional[bool] = None
    # telegram_chat_id é escrito apenas pelo webhook do bot, não exposto aqui


# ---------------------------------------------------------------------------
# Ativos
# ---------------------------------------------------------------------------

_TICKER_RE = re.compile(r'^[A-Z0-9]{1,6}$')


class AssetCreate(BaseModel):
    """Payload para adicionar um ativo à carteira."""
    ticker: Annotated[str, Field(min_length=1, max_length=6)]

    def model_post_init(self, __context) -> None:
        """Normaliza o ticker para maiúsculo antes de qualquer validação."""
        self.ticker = self.ticker.strip().upper()

    @field_validator("ticker")
    @classmethod
    def validate_ticker_format(cls, v: str) -> str:
        if not _TICKER_RE.match(v):
            raise ValueError("Ticker inválido. Use apenas letras e números (máx. 6 caracteres).")
        return v


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
