import base64
import logging
from datetime import datetime

import resend

from app.core.config import settings

resend.api_key = settings.RESEND_API_KEY

logger = logging.getLogger(__name__)


def _fmt_date(iso: str) -> str:
    try:
        return datetime.strptime(iso[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except Exception:
        return iso


def _fmt_brl(value: float | None) -> str:
    if value is None:
        return "—"
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def send_consolidated_report(
    to_email: str,
    reports_by_ticker: dict[str, list[dict]],
    user_name: str | None = None,
    attachments: list[dict] | None = None,
    dividends_map: dict[str, list[dict]] | None = None,
    tv_quotes: dict[str, dict] | None = None,
) -> bool:
    """
    Envia e-mail consolidado com relatórios, cotações e dividendos.

    reports_by_ticker: {ticker: [{title, summary, source_url, document_type}, ...]}
    attachments:       [{"filename": "...", "content": bytes}]
    dividends_map:     {ticker: [{valor_por_cota, data_base, data_pagamento, periodo, isento_ir}, ...]}
    tv_quotes:         {ticker: {price, dy_anual, dy_atual, dps, market_cap}}
    """
    tickers = list(reports_by_ticker.keys())
    count = len(tickers)
    subject = f"Summai — {count} ativo{'s' if count != 1 else ''} com novidades hoje"

    first_name = (user_name or "").split()[0] if user_name else None
    greeting = f"Olá, {first_name}!" if first_name else "Olá!"

    sections: list[str] = []

    for ticker, reports in reports_by_ticker.items():
        for report in reports:
            lines: list[str] = [report["summary"]]

            # Dividend info for this ticker
            divs = (dividends_map or {}).get(ticker, [])
            for div in divs:
                valor = div.get("valor_por_cota")
                data_base = div.get("data_base", "")
                data_pag = div.get("data_pagamento", "")
                periodo = div.get("periodo", "")
                isento = div.get("isento_ir", False)
                if valor and data_pag:
                    ir_note = " (isento IR para PF)" if isento else ""
                    lines.append(
                        f"\n💰 Dividendo {periodo}: {_fmt_brl(valor)}/cota"
                        f" · ex-data {_fmt_date(data_base)}"
                        f" · pagamento {_fmt_date(data_pag)}{ir_note}"
                    )

            # Market quote
            quote = (tv_quotes or {}).get(ticker, {})
            price = quote.get("price")
            dy = quote.get("dy_anual") or quote.get("dy_atual")
            if price:
                quote_line = f"📊 Cotação: R$ {price:.2f}"
                if dy:
                    quote_line += f" · DY anual: {dy:.2f}%"
                lines.append(f"\n{quote_line}")

            url = report.get("source_url", "")
            if url.startswith("http"):
                lines.append(f"\nRelatório completo: {url}")

            sections.append("\n".join(lines))

    divider = "\n" + "─" * 40 + "\n"
    has_attachments = bool(attachments)
    attachment_note = "\nOs PDFs dos relatórios gerenciais estão em anexo." if has_attachments else ""

    body = "\n".join([
        greeting,
        "",
        f"Hoje há novidades para {count} ativo{'s' if count != 1 else ''} da sua carteira.{attachment_note}",
        "",
        "─" * 40,
        "",
        divider.join(sections),
        "",
        "─" * 40,
        "Summai — seus ativos, resumidos.",
        "Para gerenciar suas preferências, acesse suas configurações.",
    ])

    payload: dict = {
        "from": settings.EMAIL_FROM,
        "to": [to_email],
        "subject": subject,
        "text": body,
    }

    if attachments:
        payload["attachments"] = [
            {
                "filename": att["filename"],
                "content": base64.b64encode(att["content"]).decode("utf-8"),
            }
            for att in attachments
            if att.get("content")
        ]

    try:
        resend.Emails.send(payload)
        logger.info(f"E-mail consolidado enviado para {to_email} — {tickers}")
        return True
    except Exception as e:
        logger.error(f"Erro ao enviar e-mail consolidado para {to_email}: {e}")
        return False


def send_admin_alert(subject: str, body: str) -> None:
    """
    Envia alerta operacional para o ADMIN_EMAIL configurado.
    Silencioso se ADMIN_EMAIL não estiver configurado.
    Usado para notificar mudanças em fontes de dados externas.
    """
    if not settings.ADMIN_EMAIL:
        return
    try:
        resend.Emails.send({
            "from": settings.EMAIL_FROM,
            "to": [settings.ADMIN_EMAIL],
            "subject": f"[Summai Alerta] {subject}",
            "text": body,
        })
        logger.info(f"Alerta admin enviado: {subject}")
    except Exception as e:
        logger.error(f"Falha ao enviar alerta admin: {e}")
