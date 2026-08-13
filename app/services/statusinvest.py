"""
Status Invest scraper for FII document and dividend discovery.

Status Invest embeds all comunicados in a JSON blob inside a `data-page` HTML attribute.
We parse this to get document metadata (type, date, FNET id) without hitting FNET's
Cloudflare-protected search API. Downloads (PDFs and dividend XMLs) go directly to
FNET downloadDocumento, which has no Cloudflare protection.

Coverage: FIIs only — FIAGROs return 200 with no data-code (treated as not found).
"""
import html as html_stdlib
import json
import logging
import re
from datetime import date

import httpx

logger = logging.getLogger(__name__)

_BASE_URL = "https://statusinvest.com.br/fundos-imobiliarios"
_DOWNLOAD_BASE = "https://fnet.bmfbovespa.com.br/fnet/publico/downloadDocumento"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# data-page="[...]" — all `"` inside the value are encoded as &quot;, so literal " only appears at boundaries
_DATA_PAGE_RE = re.compile(r'data-page="([^"]+)"')
_FNET_ID_RE = re.compile(r"exibirDocumento\?id=(\d+)", re.IGNORECASE)

_DOC_TYPE_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"relat[oó]rio\s+gerencial", re.I), "relatorio_gerencial"),
    (re.compile(r"fato\s+relevante", re.I), "fato_relevante"),
    (re.compile(r"comunicado\s+ao\s+mercado", re.I), "fato_relevante"),
]


def _classify(description: str) -> str | None:
    for pattern, doc_type in _DOC_TYPE_RULES:
        if pattern.search(description):
            return doc_type
    return None


def _rank_to_date(rank) -> date | None:
    """Converts rank integer/string (YYYYMMDD) to date."""
    try:
        s = str(rank)
        if len(s) == 8:
            return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    except (ValueError, TypeError):
        pass
    return None


def _parse_documents(html: str, since_date: date) -> list[dict] | None:
    """
    Parses Status Invest FII page HTML.

    Returns:
      None  — ticker not found (no data-code in page)
      []    — ticker found, no matching docs in window
      [...] — docs found
    """
    # Valid FII pages have data-code attribute; error pages don't
    if 'data-code="' not in html:
        return None

    # Find data-page JSON blob (first one with FNET links is the comunicados list)
    documents: list[dict] = []
    for m in _DATA_PAGE_RE.finditer(html):
        raw = html_stdlib.unescape(m.group(1))
        if "exibirDocumento" not in raw:
            continue

        try:
            entries = json.loads(raw)
        except json.JSONDecodeError:
            continue

        for entry in entries:
            description = entry.get("description", "")
            doc_type = _classify(description)
            if not doc_type:
                continue

            if entry.get("statusName", "").lower() == "inativo":
                continue

            # rank = publication date (YYYYMMDD); dataReferencia = reference period
            pub_date = _rank_to_date(entry.get("rank"))
            if pub_date is None or pub_date < since_date:
                continue

            link = entry.get("link", "")
            id_match = _FNET_ID_RE.search(link)
            if not id_match:
                continue

            doc_id = id_match.group(1)
            # Reference period for title: "30/06/2026" → "06/2026"
            data_ref = entry.get("dataReferencia", "")
            ref_label = ""
            if data_ref:
                parts = data_ref.split("/")
                if len(parts) >= 3:
                    ref_label = f"{parts[1]}/{parts[2][:4]}"

            title = f"{description} ({ref_label})" if ref_label else description

            documents.append({
                "title": title,
                "document_type": doc_type,
                "published_at": pub_date.isoformat(),
                "source_url": f"{_DOWNLOAD_BASE}?id={doc_id}",
                "raw_data": "",
            })

        break  # first data-page with FNET links is the comunicados section

    return documents


_AVISO_COTISTAS_RE = re.compile(r"aviso\s+aos\s+cotistas", re.I)
_RENDIMENTOS_RE = re.compile(r"rendimentos\s+e\s+amortiza", re.I)


def _parse_dividend_entries(html: str, since_date: date) -> list[tuple[str, date]]:
    """
    Extracts (fnet_doc_id, pub_date) for 'Aviso aos Cotistas / Rendimentos e Amortizações'
    entries from the Status Invest data-page JSON.
    """
    entries_out: list[tuple[str, date]] = []
    for m in _DATA_PAGE_RE.finditer(html):
        raw = html_stdlib.unescape(m.group(1))
        if "exibirDocumento" not in raw:
            continue
        try:
            entries = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for entry in entries:
            description = entry.get("description", "")
            if not (_AVISO_COTISTAS_RE.search(description) and _RENDIMENTOS_RE.search(description)):
                continue
            if entry.get("statusName", "").lower() == "inativo":
                continue
            pub_date = _rank_to_date(entry.get("rank"))
            if pub_date is None or pub_date < since_date:
                continue
            link = entry.get("link", "")
            id_match = _FNET_ID_RE.search(link)
            if not id_match:
                continue
            entries_out.append((id_match.group(1), pub_date))
        break
    return entries_out


async def fetch_fii_dividends(ticker: str, since_date: date) -> list[dict]:
    """
    Fetches FII dividend announcements from Status Invest + FNET XML download.
    Bypasses FNET search (Cloudflare) entirely — uses only FNET downloadDocumento.

    Returns list of dicts matching fnet.fetch_fii_dividends format:
      {ticker, valor_por_cota, data_base, data_pagamento, periodo, isento_ir, published_at}
    Returns [] on any failure (non-fatal — caller treats dividends as supplementary).
    """
    from app.services.fnet import _parse_dividend_xml  # avoid circular at module level

    url = f"{_BASE_URL}/{ticker.lower()}"
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            r = await client.get(url, headers=_HEADERS)
            r.raise_for_status()
            html = r.text

            if 'data-code="' not in html:
                return []

            dividend_entries = _parse_dividend_entries(html, since_date)
            if not dividend_entries:
                return []

            results: list[dict] = []
            for doc_id, pub_date in dividend_entries:
                try:
                    xml_r = await client.get(
                        f"{_DOWNLOAD_BASE}?id={doc_id}",
                        headers={"Referer": "https://fnet.bmfbovespa.com.br/"},
                        timeout=30,
                    )
                    xml_r.raise_for_status()
                    parsed = _parse_dividend_xml(xml_r.content)
                    if parsed:
                        parsed["published_at"] = pub_date.isoformat()
                        results.append(parsed)
                except Exception as e:
                    logger.warning(f"Status Invest dividendo {doc_id} para {ticker}: {e}")

            logger.info(f"Status Invest {ticker}: {len(results)} dividendo(s) desde {since_date}")
            return results
    except Exception as exc:
        logger.warning(f"Status Invest dividendos {ticker}: {exc}")
        return []


async def fetch_fii_documents(ticker: str, since_date: date) -> list[dict] | None:
    """
    Fetches recent FII documents from Status Invest.
    Returns only relatorio_gerencial and fato_relevante types.

      None  — ticker not found or network error → caller falls back to FNET
      []    — ticker found, no matching docs in window → no FNET fallback needed
      [...] — docs found
    """
    url = f"{_BASE_URL}/{ticker.lower()}"
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            r = await client.get(url, headers=_HEADERS)
            r.raise_for_status()
            html = r.text
    except Exception as exc:
        logger.warning(f"Status Invest {ticker}: {exc}")
        return None

    result = _parse_documents(html, since_date)
    if result is None:
        logger.debug(f"Status Invest: {ticker} não encontrado (sem data-code)")
    else:
        logger.info(f"Status Invest {ticker}: {len(result)} documento(s) desde {since_date}")
    return result
