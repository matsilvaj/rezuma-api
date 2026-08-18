import base64
import logging
import re
from datetime import datetime

import resend

from app.core.config import settings
from app.services.glossary import find_terms

resend.api_key = settings.RESEND_API_KEY

logger = logging.getLogger(__name__)

# ── Paleta Rezuma (espelha globals.css do rezuma-web) ─────────────────────
RZ_BG      = "#07080a"
RZ_SURFACE = "#0d0f11"
RZ_BORDER  = "rgba(237,237,234,0.07)"
RZ_BORDER_S = "rgba(237,237,234,0.10)"
RZ_TEXT    = "#ededea"
RZ_TEXT_S  = "rgba(237,237,234,0.55)"
RZ_TEXT_T  = "rgba(237,237,234,0.22)"
RZ_ACCENT  = "#5eb88a"

MONO = "'SFMono-Regular',Consolas,'Liberation Mono',Menlo,monospace"
SANS = "-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"

DOC_TYPE_LABELS = {
    "relatorio_gerencial": "relatório gerencial",
    "informe_mensal": "informe mensal",
    "fato_relevante": "fato relevante",
    "apresentacao_resultados": "apresentação de resultados",
    "itr": "resultado trimestral",
    "dfp": "resultado anual",
}

# ── Métricas (espelha dashboard/page.tsx) ─────────────────────────────────

METRIC_LABELS: dict[str, str] = {
    "rendimento_por_cota":       "rend. distribuível por cota",
    "dy_percentual":             "dividend yield",
    "dy_anualizado":             "DY anualizado",
    "valor_patrimonial_cota":    "valor patrimonial/cota",
    "pvp":                       "P/VP",
    "vacancia_percentual":       "vacância física",
    "inadimplencia_percentual":  "inadimplência",
    "receita_liquida":           "receita líquida",
    "lucro_liquido":             "lucro líquido",
    "ebitda":                    "EBITDA",
    "margem_ebitda_percentual":  "margem EBITDA",
    "margem_liquida_percentual": "margem líquida",
    "divida_liquida_ebitda":     "dívida líq./EBITDA",
    "dividendo_por_acao":        "dividendo por ação",
}

ACCENT_METRICS = {
    "rendimento_por_cota", "dy_percentual", "dy_anualizado",
    "dividendo_por_acao", "margem_liquida_percentual", "margem_ebitda_percentual",
}

PRIORITY_METRICS = [
    "rendimento_por_cota", "dy_percentual", "dy_anualizado",
    "vacancia_percentual", "pvp",
    "lucro_liquido", "receita_liquida", "margem_liquida_percentual",
    "divida_liquida_ebitda", "dividendo_por_acao",
]

METRIC_SIZES = [22, 18, 16, 14]


def _fmt_metric(key: str, value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if not isinstance(value, (int, float)):
        return str(value)

    if "rendimento" in key or "valor_patrimonial" in key or key == "dividendo_por_acao":
        return f"R${value:.2f}".replace(".", ",")
    if "percentual" in key or key in ("dy_percentual", "dy_anualizado"):
        return f"{value:.1f}".replace(".", ",") + "%"
    if key in ("pvp", "divida_liquida_ebitda"):
        return f"{value:.2f}".replace(".", ",") + "x"
    if key in ("receita_liquida", "lucro_liquido", "ebitda"):
        a = abs(value)
        if a >= 1e9:
            return f"R${value / 1e9:.1f}".replace(".", ",") + "bi"
        if a >= 1e6:
            return f"R${value / 1e6:.0f}mi"
        return f"R${value:.0f}"
    return str(value)


def _top_metrics(metrics: dict | None) -> list[dict]:
    """Top 4 métricas por prioridade, igual ao dashboard."""
    if not metrics or not isinstance(metrics, dict):
        return []
    result: list[dict] = []
    for key in PRIORITY_METRICS:
        if metrics.get(key) is not None:
            fmt = _fmt_metric(key, metrics[key])
            if fmt:
                result.append({
                    "label": METRIC_LABELS.get(key, key),
                    "value": fmt,
                    "accent": key in ACCENT_METRICS,
                })
        if len(result) == 4:
            break
    return result


# ── Helpers ───────────────────────────────────────────────────────────────

def _fmt_date(iso: str) -> str:
    try:
        return datetime.strptime(iso[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except Exception:
        return iso


def _fmt_brl(value: float | None) -> str:
    if value is None:
        return "—"
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _extract_period(title: str) -> str | None:
    """Espelha extractPeriod() do dashboard."""
    qm = re.search(r"(\d+)[Tt](\d{2,4})", title)
    if qm:
        q = int(qm.group(1))
        year = f"20{qm.group(2)}" if len(qm.group(2)) == 2 else qm.group(2)
        ords = ["1º", "2º", "3º", "4º"]
        ordinal = ords[q - 1] if 1 <= q <= 4 else f"{q}º"
        return f"{ordinal} trimestre de {year}"
    sm = re.search(r"(\d+)[Ss](\d{2,4})", title)
    if sm:
        year = f"20{sm.group(2)}" if len(sm.group(2)) == 2 else sm.group(2)
        return f"{sm.group(1)}º semestre de {year}"
    return None


def _clean(line: str) -> str:
    """Remove bullets residuais da IA."""
    return re.sub(r"^[◆•→➤▸▪–]\s*", "", line.strip())


def _md(text: str) -> str:
    """Escape HTML, converte **bold** para <strong>."""
    import html as html_lib
    escaped = html_lib.escape(_clean(text))
    return re.sub(
        r"\*\*(.+?)\*\*",
        rf'<strong style="color:{RZ_TEXT};font-weight:700;">\1</strong>',
        escaped,
    )


# ── Renderização das seções do resumo ─────────────────────────────────────

def _summary_sections(text: str) -> str:
    """DESTAQUE / citação / MOVIMENTAÇÕES / ATENÇÃO — igual ao dashboard."""
    LABEL = (
        f"font-family:{MONO};font-size:9px;font-weight:600;"
        f"letter-spacing:1.6px;text-transform:uppercase;"
        f"color:{RZ_TEXT_T};margin:0 0 12px 0;"
    )
    BODY = f"font-family:{SANS};font-size:14px;line-height:1.85;color:{RZ_TEXT_S};margin:0;"
    QUOTE = (
        f"font-family:{SANS};font-size:13px;line-height:1.75;font-style:italic;"
        f"color:rgba(237,237,234,0.40);margin:0;"
    )
    DIVIDER = (
        f'<table width="100%" cellpadding="0" cellspacing="0" style="margin:24px 0 20px 0;">'
        f'<tr><td style="height:1px;line-height:1px;font-size:0;background:{RZ_BORDER};">&nbsp;</td></tr>'
        f'</table>'
    )

    out: list[str] = []

    for raw in text.strip().split("\n"):
        line = raw.strip()
        if not line:
            continue

        if re.match(r"^DESTAQUE\s*:", line, re.IGNORECASE):
            body = re.sub(r"^DESTAQUE\s*:\s*", "", line, flags=re.IGNORECASE).strip()
            out.append(
                f'<p style="{LABEL}">Destaque</p>'
                f'<p style="{BODY}">{_md(body)}</p>'
            )

        elif re.match(r"^MOVIMENTA[ÇC][OÕ]ES\s*:", line, re.IGNORECASE):
            body = re.sub(r"^MOVIMENTA[ÇC][OÕ]ES\s*:\s*", "", line, flags=re.IGNORECASE).strip()
            out.append(
                DIVIDER
                + f'<p style="{LABEL}">Movimentações</p>'
                + f'<p style="{BODY}">{_md(body)}</p>'
            )

        elif re.match(r"^ATEN[ÇC][AÃ]O\s*:", line, re.IGNORECASE):
            body = re.sub(r"^ATEN[ÇC][AÃ]O\s*:\s*", "", line, flags=re.IGNORECASE).strip()
            if body:
                out.append(
                    f'<table width="100%" cellpadding="0" cellspacing="0" style="margin:24px 0 0 0;">'
                    f'<tr><td style="background:rgba(237,80,50,0.05);'
                    f'border:1px solid rgba(237,80,50,0.12);border-radius:6px;padding:12px 14px;">'
                    f'<p style="font-family:{MONO};font-size:9px;font-weight:600;letter-spacing:1.4px;'
                    f'text-transform:uppercase;color:rgba(237,100,80,0.55);margin:0 0 6px 0;">Atenção</p>'
                    f'<p style="font-family:{SANS};font-size:13px;line-height:1.7;'
                    f'color:rgba(237,150,130,0.70);margin:0;">{_md(body)}</p>'
                    f'</td></tr></table>'
                )

        elif line.startswith(">"):
            body = line.lstrip(">").strip()
            out.append(
                f'<table width="100%" cellpadding="0" cellspacing="0" style="margin:16px 0 0 0;">'
                f'<tr>'
                f'<td width="2" style="width:2px;background:rgba(94,184,138,0.35);font-size:0;line-height:0;">&nbsp;</td>'
                f'<td style="padding-left:16px;"><p style="{QUOTE}">{_md(body)}</p></td>'
                f'</tr></table>'
            )

        else:
            cleaned = _clean(line)
            if cleaned:
                out.append(f'<p style="{BODY}margin-top:10px;">{_md(cleaned)}</p>')

    return "".join(out)


def _glossary_box(summary: str) -> str:
    """Caixa com o significado dos termos técnicos citados no resumo."""
    terms = find_terms(summary)
    if not terms:
        return ""

    rows = ""
    for i, entry in enumerate(terms):
        pb = "14px" if i < len(terms) - 1 else "0"
        rows += (
            f'<tr><td style="padding-bottom:{pb};">'
            f'<p style="font-family:{MONO};font-size:11px;font-weight:700;'
            f'color:{RZ_TEXT};letter-spacing:0.2px;margin:0 0 4px 0;">{entry["term"]}</p>'
            f'<p style="font-family:{SANS};font-size:12px;line-height:1.65;'
            f'color:rgba(237,237,234,0.38);margin:0;">{entry["definition"]}</p>'
            f'</td></tr>'
        )

    return (
        f'<table width="100%" cellpadding="0" cellspacing="0" style="margin:24px 0 0 0;">'
        f'<tr><td style="background:rgba(237,237,234,0.02);border:1px solid {RZ_BORDER};'
        f'border-radius:6px;padding:16px 18px;">'
        f'<p style="font-family:{MONO};font-size:9px;font-weight:600;letter-spacing:1.6px;'
        f'text-transform:uppercase;color:{RZ_TEXT_T};margin:0 0 14px 0;">Glossário</p>'
        f'<table width="100%" cellpadding="0" cellspacing="0">{rows}</table>'
        f'</td></tr></table>'
    )


# ── Card de relatório (réplica do dashboard) ──────────────────────────────

def _report_card(ticker: str, report: dict, dividends: list[dict]) -> str:
    doc_key   = report.get("document_type", "")
    doc_label = DOC_TYPE_LABELS.get(doc_key, "documento")
    title     = report.get("title", "")
    period    = _extract_period(title)
    metrics   = _top_metrics(report.get("metrics"))
    source_url = report.get("source_url", "")

    # Coluna esquerda: ticker + período + métricas
    left = (
        f'<p style="font-family:{MONO};font-size:28px;font-weight:700;color:{RZ_TEXT};'
        f'letter-spacing:-1.5px;line-height:1;margin:0 0 10px 0;">{ticker}</p>'
        f'<p style="font-family:{MONO};font-size:10px;color:{RZ_TEXT_T};'
        f'letter-spacing:0.2px;line-height:1.5;margin:0;">{period or doc_label}</p>'
    )

    if metrics:
        left += '<table cellpadding="0" cellspacing="0" style="margin-top:24px;">'
        for i, m in enumerate(metrics):
            size = METRIC_SIZES[i] if i < len(METRIC_SIZES) else 14
            color = RZ_ACCENT if m["accent"] else RZ_TEXT
            pb = "16px" if i < len(metrics) - 1 else "0"
            left += (
                f'<tr><td style="padding-bottom:{pb};">'
                f'<p style="font-family:{MONO};font-size:{size}px;font-weight:700;color:{color};'
                f'letter-spacing:-0.5px;line-height:1;margin:0;">{m["value"]}</p>'
                f'<p style="font-family:{MONO};font-size:9px;color:{RZ_TEXT_T};'
                f'letter-spacing:0.2px;margin:4px 0 0 0;">{m["label"]}</p>'
                f'</td></tr>'
            )
        left += '</table>'

    # Coluna direita: seções do resumo
    right = _summary_sections(report.get("summary", ""))

    # Dividendos
    for div in dividends:
        valor    = div.get("valor_por_cota")
        data_pag = div.get("data_pagamento", "")
        data_base = div.get("data_base", "")
        if valor and data_pag:
            ir = " &middot; isento IR" if div.get("isento_ir") else ""
            right += (
                f'<table width="100%" cellpadding="0" cellspacing="0" style="margin:16px 0 0 0;">'
                f'<tr><td style="background:rgba(94,184,138,0.06);'
                f'border:1px solid rgba(94,184,138,0.15);border-radius:6px;padding:10px 14px;">'
                f'<p style="font-family:{MONO};font-size:12px;color:{RZ_ACCENT};'
                f'font-weight:600;margin:0;">'
                f'{_fmt_brl(valor)}/cota &middot; pag. {_fmt_date(data_pag)}'
                f' &middot; ex-data {_fmt_date(data_base)}{ir}</p>'
                f'</td></tr></table>'
            )

    # Glossário dos termos técnicos citados
    right += _glossary_box(report.get("summary", ""))

    # Rodapé do card: entregue via + documento
    right += (
        f'<table width="100%" cellpadding="0" cellspacing="0" style="margin:24px 0 0 0;">'
        f'<tr><td style="height:1px;line-height:1px;font-size:0;background:{RZ_BORDER};">&nbsp;</td></tr>'
        f'</table>'
        f'<table width="100%" cellpadding="0" cellspacing="0" style="margin-top:20px;">'
        f'<tr>'
        f'<td valign="top">'
        f'<p style="font-family:{MONO};font-size:9px;font-weight:600;letter-spacing:1.6px;'
        f'text-transform:uppercase;color:{RZ_TEXT_T};margin:0 0 10px 0;">Entregue via</p>'
        f'<span style="font-family:{MONO};font-size:10px;color:{RZ_TEXT_T};'
        f'border:1px solid {RZ_BORDER_S};border-radius:5px;padding:3px 10px;">e-mail</span>'
        f'</td>'
    )
    if source_url.startswith("http"):
        right += (
            f'<td valign="top" align="right">'
            f'<p style="font-family:{MONO};font-size:9px;font-weight:600;letter-spacing:1.6px;'
            f'text-transform:uppercase;color:{RZ_TEXT_T};margin:0 0 10px 0;">Documento</p>'
            f'<a href="{source_url}" style="font-family:{MONO};font-size:10px;color:{RZ_TEXT_T};'
            f'text-decoration:underline;">ver original</a>'
            f'</td>'
        )
    right += '</tr></table>'

    # Card completo
    return (
        f'<table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:16px;'
        f'background:{RZ_SURFACE};border:1px solid {RZ_BORDER};border-radius:10px;">'
        # Breadcrumb
        f'<tr><td colspan="2" style="padding:18px 24px 0 24px;">'
        f'<p style="font-family:{MONO};font-size:10px;color:{RZ_TEXT_T};'
        f'letter-spacing:0.3px;margin:0 0 7px 0;">'
        f'relatórios / {ticker.lower()} / {doc_label}</p>'
        f'<p style="font-family:{SANS};font-size:14px;font-weight:500;'
        f'color:rgba(237,237,234,0.45);line-height:1.4;margin:0;">{title}</p>'
        f'</td></tr>'
        f'<tr><td colspan="2" style="padding:16px 24px 0 24px;">'
        f'<table width="100%" cellpadding="0" cellspacing="0">'
        f'<tr><td style="height:1px;line-height:1px;font-size:0;background:{RZ_BORDER};">&nbsp;</td></tr>'
        f'</table></td></tr>'
        # Duas colunas
        f'<tr>'
        f'<td class="rz-left" width="180" valign="top" '
        f'style="width:180px;padding:24px;border-right:1px solid {RZ_BORDER};">{left}</td>'
        f'<td class="rz-right" valign="top" style="padding:24px;">{right}</td>'
        f'</tr>'
        f'</table>'
    )


def _build_html(
    greeting: str,
    reports_by_ticker: dict[str, list[dict]],
    dividends_map: dict[str, list[dict]],
    has_attachments: bool,
) -> str:
    cards = "".join(
        _report_card(ticker, report, dividends_map.get(ticker, []))
        for ticker, reports in reports_by_ticker.items()
        for report in reports
    )

    tickers_str = ", ".join(reports_by_ticker.keys())
    plural = "s" if len(reports_by_ticker) != 1 else ""

    attachment_note = (
        f'<p style="font-family:{SANS};font-size:13px;color:{RZ_TEXT_T};margin:0 0 16px 0;">'
        f'PDFs em anexo.</p>'
    ) if has_attachments else ""

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<meta name="color-scheme" content="dark">
<title>Rezuma</title>
<style>
  @media only screen and (max-width:620px) {{
    .rz-left, .rz-right {{
      display:block !important;
      width:100% !important;
      border-right:none !important;
      box-sizing:border-box !important;
    }}
    .rz-left {{
      border-bottom:1px solid {RZ_BORDER} !important;
      padding-bottom:20px !important;
    }}
  }}
</style>
</head>
<body style="margin:0;padding:0;background:{RZ_BG};">
<table width="100%" cellpadding="0" cellspacing="0" style="background:{RZ_BG};">
<tr><td align="center" style="padding:36px 16px;">
<table width="640" cellpadding="0" cellspacing="0" style="max-width:640px;width:100%;">

  <tr><td style="padding:0 0 28px 0;">
    <span style="font-family:{SANS};font-size:17px;font-weight:700;color:{RZ_TEXT};
                 letter-spacing:-0.5px;">rezuma</span>
  </td></tr>

  <tr><td style="padding:0 0 24px 0;">
    <p style="font-family:{SANS};font-size:20px;font-weight:700;color:{RZ_TEXT};
              letter-spacing:-0.3px;margin:0 0 4px 0;">{greeting}</p>
    <p style="font-family:{SANS};font-size:14px;color:{RZ_TEXT_S};margin:0;">
      Novo{plural} relatório{plural} publicado{plural}:
      <span style="color:rgba(237,237,234,0.70);">{tickers_str}</span>
    </p>
  </td></tr>

  <tr><td>{attachment_note}{cards}</td></tr>

  <tr><td style="padding:24px 0 0 0;border-top:1px solid {RZ_BORDER};text-align:center;">
    <p style="font-family:{SANS};font-size:11px;color:rgba(237,237,234,0.15);margin:0;">
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
    Envia e-mail transacional replicando o layout do dashboard.

    reports_by_ticker: {ticker: [{title, summary, source_url, document_type, metrics}, ...]}
    attachments:       [{"filename": "...", "content": bytes}]
    dividends_map:     {ticker: [{valor_por_cota, data_base, data_pagamento, isento_ir}, ...]}
    """
    tickers = list(reports_by_ticker.keys())
    count = len(tickers)

    import html as _html
    first_name = (user_name or "").split()[0] if user_name else None
    greeting = f"Olá, {_html.escape(first_name)}!" if first_name else "Olá!"

    dividends_map = dividends_map or {}

    if count == 1:
        ticker = tickers[0]
        n_docs = len(reports_by_ticker[ticker])
        label = "novo relatório publicado" if n_docs == 1 else f"{n_docs} novos documentos"
        subject = f"{ticker}: {label}"
    else:
        subject = f"{', '.join(tickers)}: novos relatórios publicados"

    html_body = _build_html(
        greeting=greeting,
        reports_by_ticker=reports_by_ticker,
        dividends_map=dividends_map,
        has_attachments=bool(attachments),
    )

    # Fallback em texto puro
    text_lines: list[str] = [greeting, ""]
    for ticker, reports in reports_by_ticker.items():
        for report in reports:
            text_lines.append(f"{ticker} — {report.get('title', '')}")
            text_lines.append("")
            text_lines.append(re.sub(r"\*\*(.+?)\*\*", r"\1", report.get("summary", "")))
            for div in dividends_map.get(ticker, []):
                valor = div.get("valor_por_cota")
                data_pag = div.get("data_pagamento", "")
                if valor and data_pag:
                    text_lines.append(
                        f"Dividendo {_fmt_brl(valor)}/cota"
                        f" · ex {_fmt_date(div.get('data_base', ''))}"
                        f" · pag. {_fmt_date(data_pag)}"
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
            "List-Unsubscribe": (
                f"<mailto:{settings.EMAIL_FROM.split('<')[-1].rstrip('>')}?subject=unsubscribe>"
            ),
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
