import logging
import re
import html as html_lib

from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError

from app.core.config import settings

logger = logging.getLogger(__name__)


def _md(text: str) -> str:
    """Escape HTML então converte **bold** para <b>bold</b>."""
    escaped = html_lib.escape(text)
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)


def _summary_to_telegram(text: str) -> str:
    """Converte resumo DESTAQUE/MOVIMENTAÇÕES para HTML do Telegram."""
    parts: list[str] = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line:
            parts.append("")
            continue
        if line.startswith("DESTAQUE:"):
            body = line[len("DESTAQUE:"):].strip()
            parts.append(f"<b>DESTAQUE</b>\n{_md(body)}")
        elif line.startswith("MOVIMENTAÇÕES:"):
            body = line[len("MOVIMENTAÇÕES:"):].strip()
            parts.append(f"\n<b>MOVIMENTAÇÕES</b>\n{_md(body)}")
        elif line.startswith("> "):
            parts.append(f"<i>{_md(line[2:].strip())}</i>")
        elif line.startswith("⚠️"):
            parts.append(_md(line))
        elif line.startswith("📌"):
            parts.append(_md(line))
        else:
            parts.append(_md(line))
    return "\n".join(parts).strip()


async def send_message(chat_id: int | str, text: str) -> bool:
    """Envia mensagem de texto simples."""
    if not settings.TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN não configurado, mensagem não enviada.")
        return False
    try:
        async with Bot(token=settings.TELEGRAM_BOT_TOKEN) as bot:
            await bot.send_message(chat_id=int(chat_id), text=text)
        return True
    except TelegramError as e:
        logger.error(f"Erro ao enviar mensagem Telegram para chat_id {chat_id}: {e}")
        return False


async def send_backfill_ready(chat_id: str, found: list[dict]) -> bool:
    """
    Avisa que a busca inicial de relatórios terminou, com link para o app.

    found: [{"ticker": "BBAS3", "count": 9}, ...], só ativos que renderam
    algum relatório. Enviado uma vez por lote de cadastro.
    """
    if not settings.TELEGRAM_BOT_TOKEN or not found:
        return False

    total  = sum(f["count"] for f in found)
    plural = "s" if total != 1 else ""

    linhas = [
        f"<b>{total} relatório{plural} pronto{plural}</b>",
        "",
        "Terminamos de buscar as publicações dos últimos 2 meses dos ativos que você adicionou:",
        "",
    ]
    for item in found:
        n = item["count"]
        linhas.append(f"<code>{item['ticker']}</code> · {n} relatório{'s' if n != 1 else ''}")

    url = f"{settings.FRONTEND_URL.rstrip('/')}/dashboard"
    linhas += ["", f'<a href="{url}">ver relatório</a>']

    try:
        async with Bot(token=settings.TELEGRAM_BOT_TOKEN) as bot:
            await bot.send_message(
                chat_id=int(chat_id),
                text="\n".join(linhas),
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        logger.info(f"Aviso de backfill enviado no Telegram para chat_id {chat_id}")
        return True
    except TelegramError as e:
        logger.error(f"Erro ao enviar aviso de backfill para chat_id {chat_id}: {e}")
        return False


async def send_consolidated_reports(
    chat_id: str,
    reports_by_ticker: dict[str, list[dict]],
) -> bool:
    """
    Envia todos os relatórios do dia em sequência:
    1. Mensagem de abertura com a lista de ativos.
    2. Uma mensagem por relatório com ticker + resumo formatado + link.

    reports_by_ticker: {ticker: [{title, summary, source_url, document_type}, ...]}
    """
    if not settings.TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN não configurado, relatório não enviado.")
        return False

    tickers = list(reports_by_ticker.keys())
    total = sum(len(v) for v in reports_by_ticker.values())
    plural = "s" if total != 1 else ""

    ticker_list = "  ".join(f"<code>{t}</code>" for t in tickers)
    header = f"📋 <b>{total} relatório{plural} hoje</b>\n{ticker_list}"

    messages: list[str] = [header]

    for ticker, reports in reports_by_ticker.items():
        for report in reports:
            summary = _summary_to_telegram(report.get("summary", ""))
            url = report.get("source_url", "")
            link = f'\n\n🔗 <a href="{url}">ver relatório original</a>' if url.startswith("http") else ""
            messages.append(f"<b>{ticker}</b>\n\n{summary}{link}")

    try:
        async with Bot(token=settings.TELEGRAM_BOT_TOKEN) as bot:
            for msg in messages:
                await bot.send_message(
                    chat_id=int(chat_id),
                    text=msg,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
        logger.info(f"Telegram consolidado enviado para chat_id {chat_id}, {tickers}")
        return True
    except TelegramError as e:
        logger.error(f"Erro ao enviar Telegram para chat_id {chat_id}: {e}")
        return False


async def send_asset_report(chat_id: str, ticker: str, reports: list[dict]) -> bool:
    """Atalho para envio de um único ativo. Usa send_consolidated_reports internamente."""
    return await send_consolidated_reports(chat_id, {ticker: reports})
