import logging
import re
import html as html_lib

from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError

from app.core.config import settings
from app.services.glossary import find_terms
from app.services.email import (
    _pick_priority, _fmt_metric, _extract_period,
    METRIC_LABELS, DOC_TYPE_LABELS,
)

logger = logging.getLogger(__name__)


def _md(text: str) -> str:
    """Escape HTML e converte **bold** para <b>bold</b>."""
    cleaned = re.sub(r"^[◆•→➤▸▪]\s*", "", text.strip())
    escaped = html_lib.escape(cleaned)
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)


def _format_summary(text: str) -> str:
    """Renderiza as seções DESTAQUE/MOVIMENTAÇÕES/ATENÇÃO/IMPACTO para HTML do Telegram."""
    parts: list[str] = []

    for raw in text.strip().split("\n"):
        line = raw.strip()
        if not line:
            continue

        if re.match(r"^DESTAQUE\s*:", line, re.IGNORECASE):
            body = re.sub(r"^DESTAQUE\s*:\s*", "", line, flags=re.IGNORECASE).strip()
            parts.append(f"<b>DESTAQUE</b>\n{_md(body)}")

        elif re.match(r"^MOVIMENTA[ÇC][OÕ]ES\s*:", line, re.IGNORECASE):
            body = re.sub(r"^MOVIMENTA[ÇC][OÕ]ES\s*:\s*", "", line, flags=re.IGNORECASE).strip()
            parts.append(f"\n<b>MOVIMENTAÇÕES</b>\n{_md(body)}")

        elif re.match(r"^ATEN[ÇC][AÃ]O\s*:", line, re.IGNORECASE):
            body = re.sub(r"^ATEN[ÇC][AÃ]O\s*:\s*", "", line, flags=re.IGNORECASE).strip()
            if body:
                parts.append(f"\n<b>ATENÇÃO</b>\n{_md(body)}")

        elif re.match(r"^IMPACTO\s*:", line, re.IGNORECASE):
            body = re.sub(r"^IMPACTO\s*:\s*", "", line, flags=re.IGNORECASE).strip()
            if body:
                parts.append(f"\n<b>O QUE MUDA PARA VOCÊ</b>\n{_md(body)}")

        elif line.startswith(">"):
            body = line.lstrip(">").strip()
            parts.append(f"\n<i>{_md(body)}</i>")

        else:
            parts.append(_md(line))

    return "\n".join(parts).strip()


def _format_metrics(metrics: dict) -> str:
    """Top 4 métricas formatadas, mesma lógica do e-mail/dashboard."""
    if not metrics or not isinstance(metrics, dict):
        return ""

    lines: list[str] = []
    for key in _pick_priority(metrics):
        if metrics.get(key) is not None:
            fmt = _fmt_metric(key, metrics[key])
            label = METRIC_LABELS.get(key, key)
            if fmt:
                lines.append(f"<code>{fmt}</code>  {label}")
        if len(lines) == 4:
            break

    return "\n".join(lines) if lines else ""


def _format_glossary(summary: str) -> str:
    """Glossário compacto dos termos técnicos citados no resumo."""
    terms = find_terms(summary)
    if not terms:
        return ""

    lines = ["<b>GLOSSÁRIO</b>"]
    for entry in terms:
        lines.append(f"<b>{html_lib.escape(entry['term'])}</b>, {html_lib.escape(entry['definition'])}")

    return "\n".join(lines)


def _report_header(ticker: str, report: dict) -> str:
    """Cabeçalho: TICKER · período ou tipo de documento."""
    title = report.get("title", "")
    doc_type = report.get("document_type", "")
    period = _extract_period(title)
    label = period or DOC_TYPE_LABELS.get(doc_type, "documento")
    return f"<b>{html_lib.escape(ticker)}</b> · {html_lib.escape(label)}"


def _report_links(report: dict) -> str:
    """Links para dashboard e documento original."""
    parts: list[str] = []

    report_id = report.get("report_id", "")
    if report_id:
        dashboard_url = f"{settings.FRONTEND_URL.rstrip('/')}/dashboard/{report_id}"
        parts.append(f'<a href="{dashboard_url}">ver no rezuma</a>')

    source_url = report.get("source_url", "")
    if source_url.startswith("http"):
        # O link vem da CVM: aspas nele fechariam o atributo href.
        parts.append(f'<a href="{html_lib.escape(source_url, quote=True)}">ver documento original</a>')

    return " · ".join(parts) if parts else ""


async def send_message(chat_id: int | str, text: str) -> bool:
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
    if not settings.TELEGRAM_BOT_TOKEN or not found:
        return False

    total = sum(f["count"] for f in found)
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
    linhas += ["", f'<a href="{url}">ver no rezuma</a>']

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
    if not settings.TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN não configurado, relatório não enviado.")
        return False

    tickers = list(reports_by_ticker.keys())
    total = sum(len(v) for v in reports_by_ticker.values())
    plural = "s" if total != 1 else ""

    ticker_list = "  ".join(f"<code>{t}</code>" for t in tickers)
    header = f"<b>{total} relatório{plural} hoje</b>\n{ticker_list}"

    messages: list[str] = [header]

    for ticker, reports in reports_by_ticker.items():
        for report in reports:
            blocks: list[str] = []

            blocks.append(_report_header(ticker, report))

            metrics_text = _format_metrics(report.get("metrics", {}))
            if metrics_text:
                blocks.append(f"\n{metrics_text}")

            summary = report.get("summary", "")
            formatted = _format_summary(summary)
            if formatted:
                blocks.append(f"\n{formatted}")

            glossary = _format_glossary(summary)
            if glossary:
                blocks.append(f"\n{glossary}")

            links = _report_links(report)
            if links:
                blocks.append(f"\n{links}")

            messages.append("\n".join(blocks))

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
    return await send_consolidated_reports(chat_id, {ticker: reports})
