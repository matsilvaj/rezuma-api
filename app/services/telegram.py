import logging

from telegram import Bot
from telegram.error import TelegramError

from app.core.config import settings

logger = logging.getLogger(__name__)

_bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)


async def send_message(chat_id: int, text: str) -> bool:
    """Envia mensagem simples de sistema (ex: confirmação de vinculação)."""
    try:
        await _bot.send_message(chat_id=chat_id, text=text)
        return True
    except TelegramError as e:
        logger.error(f"Erro ao enviar mensagem Telegram: {e}")
        return False


async def send_asset_report(chat_id: str, ticker: str, reports: list[dict]) -> bool:
    """
    Envia uma mensagem por ativo com todos os relatórios do dia agrupados.
    reports: [{title, summary, source_url}, ...]
    """
    parts = []
    for report in reports:
        parts.append(report["summary"])
        parts.append(f"🔗 [Ver documento]({report['source_url']})")

    message = "\n\n─────────────────\n\n".join(parts)
    message += "\n\n_Summai · seus ativos, resumidos_"

    try:
        await _bot.send_message(
            chat_id=chat_id,
            text=message,
            parse_mode="Markdown",
        )
        logger.info(f"Telegram enviado para chat_id {chat_id} — {ticker}")
        return True
    except TelegramError as e:
        logger.error(f"Erro ao enviar Telegram para chat_id {chat_id} — {ticker}: {e}")
        return False
