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


def _summary_to_html(text: str) -> str:
    """Converte o texto do resumo gerado pela IA em HTML formatado."""
    import html as html_lib
    paragraphs = text.strip().split("\n\n")
    html_parts: list[str] = []

    for i, block in enumerate(paragraphs):
        lines = block.strip().split("\n")
        block_html_lines: list[str] = []

        for line in lines:
            escaped = html_lib.escape(line)

            # Primeira linha do primeiro bloco é o cabeçalho (ex: "📊 HGLG11 — 07/2026")
            if i == 0 and line == lines[0]:
                block_html_lines.append(
                    f'<p style="margin:0 0 16px 0;font-size:18px;font-weight:700;color:#0f172a;">{escaped}</p>'
                )
                continue

            # Linhas de aviso (⚠️)
            if line.startswith("⚠️"):
                block_html_lines.append(
                    f'<p style="margin:0;padding:10px 14px;background:#fef9c3;border-left:3px solid #f59e0b;'
                    f'border-radius:4px;color:#78350f;font-size:14px;">{escaped}</p>'
                )
                continue

            # Linhas de destaque com → (exemplo de valor concreto)
            if line.startswith("→"):
                block_html_lines.append(
                    f'<p style="margin:4px 0 0 0;font-size:13px;color:#475569;">{escaped}</p>'
                )
                continue

            # Linhas de guidance (📌)
            if line.startswith("📌"):
                block_html_lines.append(
                    f'<p style="margin:0;font-size:14px;color:#1e40af;">{escaped}</p>'
                )
                continue

            block_html_lines.append(
                f'<p style="margin:0;font-size:15px;line-height:1.6;color:#334155;">{escaped}</p>'
            )

        if block_html_lines:
            html_parts.append(
                f'<div style="margin-bottom:16px;">{"".join(block_html_lines)}</div>'
            )

    return "".join(html_parts)


def _build_html(
    greeting: str,
    count: int,
    reports_by_ticker: dict[str, list[dict]],
    dividends_map: dict[str, list[dict]],
    tv_quotes: dict[str, dict],
    has_attachments: bool,
) -> str:
    """Monta o HTML completo do e-mail consolidado."""

    # ── Cards por ativo ────────────────────────────────────────────────────
    cards_html = ""
    doc_type_labels = {
        "relatorio_gerencial": "Relatório Gerencial",
        "informe_mensal": "Informe Mensal",
        "fato_relevante": "Fato Relevante",
        "apresentacao_resultados": "Apresentação de Resultados",
        "itr": "Resultado Trimestral",
        "dfp": "Resultado Anual",
    }

    for ticker, reports in reports_by_ticker.items():
        divs = dividends_map.get(ticker, [])
        quote = tv_quotes.get(ticker, {})
        price = quote.get("price")
        dy = quote.get("dy_anual") or quote.get("dy_atual")

        for report in reports:
            doc_label = doc_type_labels.get(report.get("document_type", ""), "Documento")
            summary_html = _summary_to_html(report.get("summary", ""))
            source_url = report.get("source_url", "")

            # Dividend pill
            div_html = ""
            for div in divs:
                valor = div.get("valor_por_cota")
                data_pag = div.get("data_pagamento", "")
                data_base = div.get("data_base", "")
                isento = div.get("isento_ir", False)
                if valor and data_pag:
                    ir = " · isento IR para PF" if isento else ""
                    div_html += (
                        f'<div style="display:inline-block;margin:4px 4px 0 0;padding:6px 12px;'
                        f'background:#dcfce7;border-radius:20px;font-size:13px;color:#15803d;font-weight:600;">'
                        f'💰 Dividendo {_fmt_brl(valor)}/cota · pagamento {_fmt_date(data_pag)}'
                        f' · ex-data {_fmt_date(data_base)}{ir}</div>'
                    )

            # Quote row
            quote_html = ""
            if price:
                dy_str = f" &nbsp;·&nbsp; DY anual: {dy:.2f}%" if dy else ""
                quote_html = (
                    f'<div style="margin-top:12px;padding:10px 14px;background:#f8fafc;'
                    f'border-radius:6px;font-size:13px;color:#475569;">'
                    f'📊 Cotação: <strong style="color:#0f172a;">R$ {price:.2f}</strong>{dy_str}</div>'
                )

            # Report link button
            link_html = ""
            if source_url.startswith("http"):
                link_html = (
                    f'<div style="margin-top:16px;">'
                    f'<a href="{source_url}" style="display:inline-block;padding:8px 18px;'
                    f'background:#0f172a;color:#ffffff;text-decoration:none;border-radius:6px;'
                    f'font-size:13px;font-weight:600;">Ver relatório completo →</a></div>'
                )

            cards_html += f"""
            <div style="margin-bottom:24px;background:#ffffff;border:1px solid #e2e8f0;
                        border-radius:10px;overflow:hidden;">
              <!-- Card header -->
              <div style="padding:14px 20px;background:#f8fafc;border-bottom:1px solid #e2e8f0;
                          display:flex;align-items:center;gap:10px;">
                <span style="font-size:16px;font-weight:800;color:#0f172a;">{ticker}</span>
                <span style="padding:2px 10px;background:#e2e8f0;border-radius:20px;
                             font-size:12px;color:#475569;font-weight:500;">{doc_label}</span>
              </div>
              <!-- Card body -->
              <div style="padding:20px;">
                {summary_html}
                {div_html}
                {quote_html}
                {link_html}
              </div>
            </div>
            """

    attachment_note = (
        '<p style="margin:0 0 24px 0;font-size:14px;color:#64748b;">'
        '📎 Os PDFs estão em anexo neste e-mail.</p>'
    ) if has_attachments else ""

    # ── Template completo ──────────────────────────────────────────────────
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
  <title>Rezuma</title>
</head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f1f5f9;">
    <tr><td align="center" style="padding:32px 16px;">

      <!-- Container -->
      <table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;">

        <!-- Header -->
        <tr><td style="background:#0f172a;border-radius:10px 10px 0 0;padding:24px 32px;">
          <span style="font-size:22px;font-weight:800;color:#ffffff;letter-spacing:-0.5px;">Rezuma</span>
          <span style="font-size:14px;color:#94a3b8;margin-left:10px;">seus ativos, resumidos</span>
        </td></tr>

        <!-- Body -->
        <tr><td style="background:#ffffff;padding:32px;border-left:1px solid #e2e8f0;border-right:1px solid #e2e8f0;">

          <p style="margin:0 0 8px 0;font-size:20px;font-weight:700;color:#0f172a;">{greeting}</p>
          <p style="margin:0 0 28px 0;font-size:15px;color:#475569;">
            Hoje há novidades para <strong>{count} ativo{'s' if count != 1 else ''}</strong> da sua carteira.
          </p>

          {attachment_note}
          {cards_html}

        </td></tr>

        <!-- Footer -->
        <tr><td style="background:#f8fafc;border:1px solid #e2e8f0;border-top:none;
                        border-radius:0 0 10px 10px;padding:20px 32px;text-align:center;">
          <p style="margin:0;font-size:13px;color:#94a3b8;">
            Rezuma · Você está recebendo este e-mail porque monitora ativos na plataforma.
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
    Envia e-mail consolidado com relatórios, cotações e dividendos.

    reports_by_ticker: {ticker: [{title, summary, source_url, document_type}, ...]}
    attachments:       [{"filename": "...", "content": bytes}]
    dividends_map:     {ticker: [{valor_por_cota, data_base, data_pagamento, periodo, isento_ir}, ...]}
    tv_quotes:         {ticker: {price, dy_anual, dy_atual, dps, market_cap}}
    """
    tickers = list(reports_by_ticker.keys())
    count = len(tickers)
    subject = f"Rezuma — {count} ativo{'s' if count != 1 else ''} com novidades hoje"

    import html as _html
    first_name = (user_name or "").split()[0] if user_name else None
    greeting = f"Olá, {_html.escape(first_name)}!" if first_name else "Olá!"

    dividends_map = dividends_map or {}
    tv_quotes = tv_quotes or {}

    # ── HTML ──────────────────────────────────────────────────────────────
    html_body = _build_html(
        greeting=greeting,
        count=count,
        reports_by_ticker=reports_by_ticker,
        dividends_map=dividends_map,
        tv_quotes=tv_quotes,
        has_attachments=bool(attachments),
    )

    # ── Plain text fallback ───────────────────────────────────────────────
    text_sections: list[str] = []
    for ticker, reports in reports_by_ticker.items():
        for report in reports:
            lines: list[str] = [report["summary"]]
            for div in dividends_map.get(ticker, []):
                valor = div.get("valor_por_cota")
                data_pag = div.get("data_pagamento", "")
                data_base = div.get("data_base", "")
                isento = div.get("isento_ir", False)
                if valor and data_pag:
                    ir = " (isento IR para PF)" if isento else ""
                    lines.append(
                        f"\n💰 Dividendo {_fmt_brl(valor)}/cota"
                        f" · ex-data {_fmt_date(data_base)}"
                        f" · pagamento {_fmt_date(data_pag)}{ir}"
                    )
            quote = tv_quotes.get(ticker, {})
            price = quote.get("price")
            dy = quote.get("dy_anual") or quote.get("dy_atual")
            if price:
                dy_str = f" · DY anual: {dy:.2f}%" if dy else ""
                lines.append(f"\n📊 Cotação: R$ {price:.2f}{dy_str}")
            url = report.get("source_url", "")
            if url.startswith("http"):
                lines.append(f"\nRelatório completo: {url}")
            text_sections.append("\n".join(lines))

    text_body = f"{greeting}\n\nHoje há novidades para {count} ativo{'s' if count != 1 else ''} da sua carteira.\n\n"
    text_body += ("\n\n" + "─" * 40 + "\n\n").join(text_sections)
    text_body += "\n\n─" * 40 + "\nRezuma — seus ativos, resumidos."

    # ── Envio ─────────────────────────────────────────────────────────────
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
    """
    Envia alerta operacional para o ADMIN_EMAIL configurado.
    Silencioso se ADMIN_EMAIL não estiver configurado.
    """
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
