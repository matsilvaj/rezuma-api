import base64
import logging
import re
from datetime import datetime

import resend

from app.core.config import settings

resend.api_key = settings.RESEND_API_KEY

logger = logging.getLogger(__name__)

RZ_BG       = "#07080a"
RZ_SURFACE  = "#0d0f11"
RZ_BORDER   = "rgba(237,237,234,0.07)"
RZ_TEXT     = "#ededea"
RZ_MUTED    = "rgba(237,237,234,0.40)"
RZ_FAINT    = "rgba(237,237,234,0.20)"
RZ_ACCENT   = "#5eb88a"


def _fmt_date(iso: str) -> str:
    try:
        return datetime.strptime(iso[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except Exception:
        return iso


def _fmt_brl(value: float | None) -> str:
    if value is None:
        return "—"
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _md(text: str) -> str:
    """Escape HTML then convert **bold** to <strong>."""
    import html as html_lib
    escaped = html_lib.escape(text)
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)


def _summary_to_html(text: str) -> str:
    """Converte resumo em HTML com tema escuro Rezuma."""
    LABEL = (
        f"font-family:monospace;font-size:10px;font-weight:600;"
        f"letter-spacing:2px;text-transform:uppercase;"
        f"color:{RZ_FAINT};margin:0 0 6px 0;display:block;"
    )
    BODY = (
        f"margin:0;font-size:14px;line-height:1.7;color:{RZ_MUTED};"
    )
    QUOTE = (
        f"margin:10px 0;padding:10px 14px;"
        f"border-left:2px solid {RZ_ACCENT};"
        f"font-size:13px;font-style:italic;color:{RZ_FAINT};"
    )
    WARN = (
        f"margin:10px 0;padding:10px 14px;"
        f"background:rgba(245,158,11,0.06);"
        f"border-left:2px solid #f59e0b;"
        f"border-radius:4px;font-size:13px;color:rgba(237,237,234,0.55);"
    )

    parts: list[str] = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue

        if line.startswith("DESTAQUE:"):
            body = line[len("DESTAQUE:"):].strip()
            parts.append(
                f'<span style="{LABEL}">DESTAQUE</span>'
                f'<p style="{BODY}">{_md(body)}</p>'
            )
        elif line.startswith("MOVIMENTAÇÕES:"):
            body = line[len("MOVIMENTAÇÕES:"):].strip()
            parts.append(
                f'<span style="{LABEL};margin-top:18px;">MOVIMENTAÇÕES</span>'
                f'<p style="{BODY}">{_md(body)}</p>'
            )
        elif line.startswith("> "):
            parts.append(f'<p style="{QUOTE}">{_md(line[2:].strip())}</p>')
        elif line.startswith("⚠️"):
            parts.append(f'<p style="{WARN}">{_md(line)}</p>')
        elif line.startswith("📌"):
            parts.append(
                f'<p style="margin:8px 0;font-size:13px;color:{RZ_ACCENT};">{_md(line)}</p>'
            )
        else:
            parts.append(f'<p style="{BODY}">{_md(line)}</p>')

    return "".join(parts)


def _build_html(
    greeting: str,
    count: int,
    reports_by_ticker: dict[str, list[dict]],
    dividends_map: dict[str, list[dict]],
    has_attachments: bool,
) -> str:
    doc_type_labels = {
        "relatorio_gerencial": "Relatório Gerencial",
        "informe_mensal": "Informe Mensal",
        "fato_relevante": "Fato Relevante",
        "apresentacao_resultados": "Apresentação de Resultados",
        "itr": "Resultado Trimestral",
        "dfp": "Resultado Anual",
    }

    cards_html = ""
    for ticker, reports in reports_by_ticker.items():
        divs = dividends_map.get(ticker, [])

        for report in reports:
            doc_label = doc_type_labels.get(report.get("document_type", ""), "Documento")
            summary_html = _summary_to_html(report.get("summary", ""))
            source_url = report.get("source_url", "")

            div_html = ""
            for div in divs:
                valor = div.get("valor_por_cota")
                data_pag = div.get("data_pagamento", "")
                data_base = div.get("data_base", "")
                isento = div.get("isento_ir", False)
                if valor and data_pag:
                    ir = " · isento IR" if isento else ""
                    div_html += (
                        f'<div style="display:inline-block;margin:14px 4px 0 0;padding:7px 14px;'
                        f'background:rgba(94,184,138,0.07);border:1px solid rgba(94,184,138,0.18);'
                        f'border-radius:20px;font-size:13px;color:{RZ_ACCENT};font-weight:600;">'
                        f'💰 {_fmt_brl(valor)}/cota &nbsp;·&nbsp; pag. {_fmt_date(data_pag)}'
                        f'&nbsp;·&nbsp; ex-data {_fmt_date(data_base)}{ir}</div>'
                    )

            link_html = ""
            if source_url.startswith("http"):
                link_html = (
                    f'<div style="margin-top:18px;">'
                    f'<a href="{source_url}" style="display:inline-block;padding:8px 18px;'
                    f'background:rgba(237,237,234,0.05);color:{RZ_MUTED};'
                    f'text-decoration:none;border-radius:6px;font-size:13px;font-weight:500;'
                    f'border:1px solid {RZ_BORDER};">ver relatório original →</a></div>'
                )

            cards_html += (
                f'<div style="margin-bottom:14px;background:{RZ_SURFACE};'
                f'border:1px solid {RZ_BORDER};border-radius:10px;overflow:hidden;">'
                f'<div style="padding:13px 20px;border-bottom:1px solid {RZ_BORDER};">'
                f'<span style="font-family:monospace;font-size:15px;font-weight:700;color:{RZ_TEXT};">{ticker}</span>'
                f'&nbsp;&nbsp;'
                f'<span style="padding:2px 10px;background:rgba(237,237,234,0.05);border-radius:20px;'
                f'font-size:11px;color:{RZ_FAINT};font-weight:500;">{doc_label}</span>'
                f'</div>'
                f'<div style="padding:20px;">'
                f'{summary_html}{div_html}{link_html}'
                f'</div>'
                f'</div>'
            )

    attachment_note = (
        f'<p style="margin:0 0 20px 0;font-size:13px;color:{RZ_FAINT};">'
        f'📎 Os PDFs estão em anexo neste e-mail.</p>'
    ) if has_attachments else ""

    plural = "s" if count != 1 else ""

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
  <title>Rezuma</title>
</head>
<body style="margin:0;padding:0;background:{RZ_BG};font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:{RZ_BG};">
    <tr><td align="center" style="padding:36px 16px;">
      <table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;">

        <!-- Logo -->
        <tr><td style="padding:0 0 32px 0;">
          <span style="font-size:18px;font-weight:700;color:{RZ_TEXT};letter-spacing:-0.5px;">rezuma</span>
        </td></tr>

        <!-- Greeting -->
        <tr><td style="padding:0 0 28px 0;">
          <p style="margin:0 0 6px 0;font-size:22px;font-weight:700;color:{RZ_TEXT};letter-spacing:-0.5px;">{greeting}</p>
          <p style="margin:0;font-size:14px;color:{RZ_MUTED};">
            Hoje há novidades para
            <strong style="color:rgba(237,237,234,0.65);">{count} ativo{plural}</strong>
            monitorado{plural}.
          </p>
        </td></tr>

        <!-- Cards -->
        <tr><td>
          {attachment_note}
          {cards_html}
        </td></tr>

        <!-- Footer -->
        <tr><td style="padding:28px 0 0 0;text-align:center;border-top:1px solid {RZ_BORDER};">
          <p style="margin:0;font-size:12px;color:rgba(237,237,234,0.18);">
            Você recebe este e-mail porque monitora ativos no Rezuma.
          </p>
        </td></tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""


def send_consolidated_report(
    to_email: str,
    reports_by_ticker: dict[str, list[dict]],
    user_name: str | None = None,
    attachments: list[dict] | None = None,
    dividends_map: dict[str, list[dict]] | None = None,
    tv_quotes: dict[str, dict] | None = None,
) -> bool:
    """
    Envia e-mail consolidado com relatórios e dividendos.

    reports_by_ticker: {ticker: [{title, summary, source_url, document_type}, ...]}
    attachments:       [{"filename": "...", "content": bytes}]
    dividends_map:     {ticker: [{valor_por_cota, data_base, data_pagamento, periodo, isento_ir}, ...]}
    tv_quotes:         reservado para uso futuro, ignorado por enquanto
    """
    tickers = list(reports_by_ticker.keys())
    count = len(tickers)
    subject = f"Rezuma — {count} ativo{'s' if count != 1 else ''} com novidades hoje"

    import html as _html
    first_name = (user_name or "").split()[0] if user_name else None
    greeting = f"Olá, {_html.escape(first_name)}!" if first_name else "Olá!"

    dividends_map = dividends_map or {}

    html_body = _build_html(
        greeting=greeting,
        count=count,
        reports_by_ticker=reports_by_ticker,
        dividends_map=dividends_map,
        has_attachments=bool(attachments),
    )

    # Plain text fallback
    text_sections: list[str] = []
    for ticker, reports in reports_by_ticker.items():
        for report in reports:
            lines: list[str] = [report.get("summary", "")]
            for div in dividends_map.get(ticker, []):
                valor = div.get("valor_por_cota")
                data_pag = div.get("data_pagamento", "")
                data_base = div.get("data_base", "")
                isento = div.get("isento_ir", False)
                if valor and data_pag:
                    ir = " (isento IR)" if isento else ""
                    lines.append(
                        f"\n💰 Dividendo {_fmt_brl(valor)}/cota"
                        f" · ex-data {_fmt_date(data_base)}"
                        f" · pagamento {_fmt_date(data_pag)}{ir}"
                    )
            url = report.get("source_url", "")
            if url.startswith("http"):
                lines.append(f"\nRelatório completo: {url}")
            text_sections.append("\n".join(lines))

    text_body = (
        f"{greeting}\n\nHoje há novidades para {count} ativo{'s' if count != 1 else ''} monitorado{'s' if count != 1 else ''}.\n\n"
        + ("\n\n" + "─" * 40 + "\n\n").join(text_sections)
        + "\n\n" + "─" * 40 + "\nRezuma — seus ativos, resumidos."
    )

    payload: dict = {
        "from": settings.EMAIL_FROM,
        "to": [to_email],
        "subject": subject,
        "html": html_body,
        "text": text_body,
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
    if not settings.ADMIN_EMAIL:
        return
    try:
        resend.Emails.send({
            "from": settings.EMAIL_FROM,
            "to": [settings.ADMIN_EMAIL],
            "subject": f"[Rezuma Alerta] {subject}",
            "text": body,
        })
        logger.info(f"Alerta admin enviado: {subject}")
    except Exception as e:
        logger.error(f"Falha ao enviar alerta admin: {e}")
