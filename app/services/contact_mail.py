"""
Aviso de nova mensagem de contato, por SMTP comum.

Fica fora do Resend de propósito: a cota gratuita de lá é do produto (resumos
e e-mails de login), e mensagem de formulário não pode competir com isso. Um
SMTP de conta comum resolve, é grátis e independente.

Nada aqui é essencial: a mensagem já foi gravada no banco antes de chegar
neste módulo. Se o envio falhar, o registro continua lá.
"""

import logging
import smtplib
from email.message import EmailMessage

from app.core.config import settings

logger = logging.getLogger(__name__)


def smtp_configurado() -> bool:
    return bool(settings.SMTP_USER and settings.SMTP_PASSWORD and settings.CONTACT_EMAIL)


def enviar_aviso_contato(nome: str, email: str, mensagem: str) -> bool:
    """
    Avisa o endereço de contato sobre uma mensagem nova.

    O corpo vai em texto puro: não há HTML para montar e, sem HTML, não há
    como o texto de terceiros virar marcação dentro do e-mail.
    """
    if not smtp_configurado():
        logger.info("SMTP de contato não configurado; mensagem ficou apenas no banco.")
        return False

    msg = EmailMessage()
    # O assunto carrega o nome, mas sem quebra de linha: um \n aqui permitiria
    # injetar cabeçalhos no e-mail.
    msg["Subject"] = f"Rezuma: mensagem de {nome[:60]}".replace("\n", " ").replace("\r", " ")
    msg["From"] = settings.SMTP_USER
    msg["To"] = settings.CONTACT_EMAIL
    # Responder vai direto para quem escreveu, sem expor o endereço no From.
    msg["Reply-To"] = email
    msg.set_content(
        f"De: {nome} <{email}>\n\n{mensagem}\n\n"
        "Mensagem enviada pelo formulário de contato do Rezuma."
    )

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20) as s:
            s.starttls()
            s.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            s.send_message(msg)
        logger.info("Aviso de contato enviado.")
        return True
    except Exception as e:
        # Sem stack trace e sem o conteúdo: o log não é lugar para a mensagem
        # nem para credencial.
        logger.error(f"Falha ao enviar aviso de contato: {type(e).__name__}")
        return False
