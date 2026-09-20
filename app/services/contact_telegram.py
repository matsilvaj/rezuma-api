"""
Entrega das mensagens do formulário de contato no Telegram de quem mantém.

Usa a API do Telegram direto por HTTP, em vez do cliente assíncrono que os
resumos usam: a rota de contato é síncrona e uma única chamada não justifica
arrastar um event loop para dentro dela.

Quem escreve não sabe nem precisa saber que o destino é o Telegram; para a
pessoa, é só o formulário de contato.
"""

import html
import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_LIMITE_TELEGRAM = 4096


def configurado() -> bool:
    return bool(settings.CONTACT_BOT_TOKEN and settings.CONTACT_CHAT_ID)


def enviar_contato(assunto: str, nome: str, email: str, mensagem: str) -> bool:
    """
    Manda a mensagem e diz se chegou.

    O retorno importa: sem banco por trás, uma falha aqui significa mensagem
    perdida, e a rota precisa avisar quem escreveu em vez de fingir sucesso.
    """
    if not configurado():
        logger.error("Contato pelo Telegram não configurado: mensagem não entregue.")
        return False

    # Tudo que veio do formulário é escapado: é texto de estranho entrando
    # num corpo em HTML.
    corpo = (
        f"<b>{html.escape(assunto)}</b>\n\n"
        f"{html.escape(mensagem)}\n\n"
        f"<b>{html.escape(nome)}</b>\n"
        f"<code>{html.escape(email)}</code>"
    )
    if len(corpo) > _LIMITE_TELEGRAM:
        corpo = corpo[: _LIMITE_TELEGRAM - 20] + "\n[cortada]"

    try:
        resposta = httpx.post(
            f"https://api.telegram.org/bot{settings.CONTACT_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": settings.CONTACT_CHAT_ID,
                "text": corpo,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=15,
        )
        resposta.raise_for_status()
        return True
    except Exception as e:
        # Sem corpo e sem token no log.
        logger.error(f"Falha ao entregar contato no Telegram: {type(e).__name__}")
        return False
