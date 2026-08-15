import logging

from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError

from app.core.config import settings

logger = logging.getLogger(__name__)


async def send_message(chat_id: int | str, text: str) -> bool:
    """Envia mensagem de texto simples. Cria Bot por chamada para evitar problemas de event loop."""
    if not settings.TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN não configurado — mensagem não enviada.")
        return False
    try:
        async with Bot(token=settings.TELEGRAM_BOT_TOKEN) as bot:
            await bot.send_message(chat_id=int(chat_id), text=text)
        return True
    except TelegramError as e:
        logger.error(f"Erro ao enviar mensagem Telegram para chat_id {chat_id}: {e}")
        return False


async def send_asset_report(chat_id: str, ticker: str, reports: list[dict]) -> bool:
    """
    Envia relatórios do dia agrupados por ativo, com formatação HTML.
    reports: [{title, summary, source_url}, ...]
    """
    if not settings.TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN não configurado — relatório não enviado.")
        return False

    parts: list[str] = []
    for report in reports:
        summary = report.get("summary", "")
        url = report.get("source_url", "")
        link = f'\n🔗 <a href="{url}">Ver documento</a>' if url.startswith("http") else ""
        parts.append(f"{summary}{link}")

    divider = "\n\n─────────────\n\n"
    message = divider.join(parts)
    message += "\n\n<i>Rezuma · seus ativos, resumidos</i>"

    try:
        async with Bot(token=settings.TELEGRAM_BOT_TOKEN) as bot:
            await bot.send_message(
                chat_id=int(chat_id),
                text=message,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        logger.info(f"Telegram enviado para chat_id {chat_id} — {ticker}")
        return True
    except TelegramError as e:
        logger.error(f"Erro ao enviar Telegram para chat_id {chat_id} — {ticker}: {e}")
        return False
