import base64
import logging
import re
from datetime import datetime

import resend

from app.core.config import settings

resend.api_key = settings.RESEND_API_KEY

logger = logging.getLogger(__name__)

RZ_BG      = "#07080a"
RZ_SURFACE = "#0d0f11"
RZ_BORDER  = "rgba(237,237,234,0.07)"
RZ_TEXT    = "#ededea"
RZ_MUTED   = "rgba(237,237,234,0.45)"
RZ_FAINT   = "rgba(237,237,234,0.20)"
RZ_ACCENT  = "#5eb88a"


def _fmt_date(iso: str) -> str:
    try:
        return datetime.strptime(iso[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except Exception:
        return iso


def _fmt_brl(value: float | None) -> str:
    if value is None:
        return "—"
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _clean(line: str) -> str:
    """Remove bullet artifacts comuns na saída da IA: ◆ • → ➤ ▸ ▪ –"""
    return re.sub(r"^[◆•→➤▸▪–]\s*", "", line.strip())


def _md(text: str) -> str:
    """Escape HTML, converte **bold** para <strong> e remove bullets residuais."""
    import html as html_lib
    cleaned = _clean(text)
    escaped = html_lib.escape(cleaned)
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)


def _summary_to_html(text: str) -> str:
    """Converte resumo DESTAQUE/MOVIMENTAÇÕES para HTML inline-style."""
    LABEL = (
        "font-family:monospace;font-size:10px;font-weight:600;"
        "letter-spacing:2px;text-transform:uppercase;"
        f"color:{RZ_FAINT};margin:0 0 8px 0;display:block;"
    )
    BODY = f"margin:0 0 10px 0;font-size:14px;line-height:1.7;color:{RZ_MUTED};"
    QUOTE = (
        f"margin:0 0 12px 0;padding:10px 14px;"
        f"border-left:2px solid {RZ_ACCENT};"
        f"font-size:13px;font-style:italic;color:{RZ_FAINT};"
    )
    WARN = (
        "margin:12px 0 0 0;padding:10px 14px;"
        "background:rgba(245,158,11,0.06);"
        "border-left:2px solid #f59e0b;"
        "border-radius:4px;font-size:13px;"
        f"color:rgba(237,237,234,0.55);"
    )

    parts: list[str] = []
    first_destaque = True

    for line in text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue

        if line.upper().startswith("DESTAQUE:"):
            body = line[len("DESTAQUE:"):].strip()
            mt = "" if first_destaque else "margin-top:18px;"
            first_destaque = False
            parts.append(
                f'<span style="{LABEL}{mt}">DESTAQUE</span>'
                f'<p style="{BODY}">{_md(body)}</p>'
            )
        elif line.upper().startswith("MOVIMENTAÇÕES:") or line.upper().startswith("MOVIMENTACOES:"):
            prefix_len = len("MOVIMENTAÇÕES:") if "Ç" in line.upper()[:15] else len("MOVIMENTACOES:")
            body = line[prefix_len:].strip()
            parts.append(
                f'<span style="{LABEL}margin-top:18px;">MOVIMENTAÇÕES</span>'
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
            # Linha solta da IA (continuação de parágrafo ou bullet residual)
            cleaned = _clean(line)
            if cleaned:
                parts.append(f'<p style="{BODY}">{_md(cleaned)}</p>')

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
                    ir = " &middot; isento IR" if isento else ""
                    div_html += (
                        f'<p style="margin:16px 0 0 0;padding:10px 14px;'
                        f'background:rgba(94,184,138,0.07);border:1px solid rgba(94,184,138,0.15);'
                        f'border-radius:8px;font-size:13px;color:{RZ_ACCENT};font-weight:600;">'
                        f'💰 {_fmt_brl(valor)}/cota &nbsp;&middot;&nbsp; pag. {_fmt_date(data_pag)}'
                        f' &nbsp;&middot;&nbsp; ex-data {_fmt_date(data_base)}{ir}</p>'
                    )

            link_html = ""
            if source_url.startswith("http"):
                link_html = (
                    f'<p style="margin:18px 0 0 0;">'
                    f'<a href="{source_url}" style="font-size:13px;color:{RZ_FAINT};text-decoration:none;">'
                    f'ver documento original →</a></p>'
                )

            cards_html += (
                f'<table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:16px;">'
                f'<tr><td style="background:{RZ_SURFACE};border:1px solid {RZ_BORDER};border-radius:10px;overflow:hidden;">'
                # Card header
                f'<table width="100%" cellpadding="0" cellspacing="0">'
                f'<tr><td style="padding:14px 20px;border-bottom:1px solid {RZ_BORDER};">'
                f'<span style="font-family:monospace;font-size:15px;font-weight:700;color:{RZ_TEXT};">{ticker}</span>'
                f'&nbsp;&nbsp;'
                f'<span style="font-size:11px;color:{RZ_FAINT};">{doc_label}</span>'
                f'</td></tr>'
                # Card body
                f'<tr><td style="padding:20px;">'
                f'{summary_html}{div_html}{link_html}'
                f'</td></tr>'
                f'</table>'
                f'</td></tr></table>'
            )

    attachment_note = (
        f'<p style="margin:0 0 20px 0;font-size:13px;color:{RZ_FAINT};">📎 PDFs em anexo.</p>'
    ) if has_attachments else ""

    tickers_str = ", ".join(reports_by_ticker.keys())
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
  <tr><td style="padding:0 0 28px 0;">
    <span style="font-size:17px;font-weight:700;color:{RZ_TEXT};letter-spacing:-0.5px;">rezuma</span>
  </td></tr>

  <!-- Intro -->
  <tr><td style="padding:0 0 24px 0;">
    <p style="margin:0 0 4px 0;font-size:20px;font-weight:700;color:{RZ_TEXT};letter-spacing:-0.3px;">{greeting}</p>
    <p style="margin:0;font-size:14px;color:{RZ_MUTED};">
      Novo{plural} relatório{plural} publicado{plural}: <span style="color:rgba(237,237,234,0.65);">{tickers_str}</span>
    </p>
  </td></tr>

  <!-- Cards -->
  <tr><td>
    {attachment_note}
    {cards_html}
  </td></tr>

  <!-- Footer -->
  <tr><td style="padding:24px 0 0 0;border-top:1px solid {RZ_BORDER};text-align:center;">
    <p style="margin:0;font-size:11px;color:rgba(237,237,234,0.15);">
      Você recebe porque monitora este ativo no Rezuma.
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
    Envia e-mail transacional com relatórios e dividendos.

    reports_by_ticker: {ticker: [{title, summary, source_url, document_type}, ...]}
    attachments:       [{"filename": "...", "content": bytes}]
    dividends_map:     {ticker: [{valor_por_cota, data_base, data_pagamento, isento_ir}, ...]}
    """
    tickers = list(reports_by_ticker.keys())
    count = len(tickers)

    import html as _html
    first_name = (user_name or "").split()[0] if user_name else None
    greeting = f"Olá, {_html.escape(first_name)}!" if first_name else "Olá!"

    dividends_map = dividends_map or {}

    # Assunto transacional — evita tab promoções do Gmail
    if count == 1:
        ticker = tickers[0]
        doc_types = {r.get("document_type") for r in reports_by_ticker[ticker]}
        label = "relatório publicado" if len(doc_types) == 1 else "documentos publicados"
        subject = f"{ticker}: novo {label}"
    else:
        subject = f"{', '.join(tickers)}: novos relatórios publicados"

    html_body = _build_html(
        greeting=greeting,
        count=count,
        reports_by_ticker=reports_by_ticker,
        dividends_map=dividends_map,
        has_attachments=bool(attachments),
    )

    # Plain text fallback
    text_lines: list[str] = [greeting, ""]
    for ticker, reports in reports_by_ticker.items():
        for report in reports:
            text_lines.append(report.get("summary", ""))
            for div in dividends_map.get(ticker, []):
                valor = div.get("valor_por_cota")
                data_pag = div.get("data_pagamento", "")
                data_base = div.get("data_base", "")
                if valor and data_pag:
                    text_lines.append(
                        f"Dividendo {_fmt_brl(valor)}/cota"
                        f" · ex {_fmt_date(data_base)} · pag. {_fmt_date(data_pag)}"
                    )
            url = report.get("source_url", "")
            if url.startswith("http"):
                text_lines.append(f"Documento: {url}")
            text_lines.append("")
    text_body = "\n".join(text_lines).strip()

    payload: dict = {
        "from": settings.EMAIL_FROM,
        "to": [to_email],
        "subject": subject,
        "html": html_body,
        "text": text_body,
        "headers": {
            # Sinaliza ao Gmail que é e-mail transacional legítimo
            "List-Unsubscribe": f"<mailto:{settings.EMAIL_FROM.split('<')[-1].rstrip('>')}?subject=unsubscribe>",
            "X-Entity-Ref-ID": f"rezuma-report-{'-'.join(tickers)}",
        },
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
        logger.info(f"E-mail enviado para {to_email} — {tickers}")
        return True
    except Exception as e:
        logger.error(f"Erro ao enviar e-mail para {to_email}: {e}")
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
