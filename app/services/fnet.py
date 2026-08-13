"""
FNET (B3 Fundos.NET) document fetcher for FII PDFs.

Uses curl-cffi with Chrome impersonation to bypass Cloudflare protection.
Covers: Relatório Gerencial (monthly) and Fato Relevante (event-based).

The Relatório Gerencial is a B3/FNET-exclusive document — CVM only receives
the Informe Mensal Estruturado (CSV), which is a different, less detailed report.
"""
import asyncio
import logging
import xml.etree.ElementTree as ET
from datetime import date, datetime

import httpx
from curl_cffi.requests import AsyncSession

logger = logging.getLogger(__name__)

_BASE = "https://fnet.bmfbovespa.com.br/fnet/publico"
_PAGE_URL = f"{_BASE}/pesquisarGerenciadorDocumentosCVM"
_LIST_URL = f"{_BASE}/pesquisarGerenciadorDocumentosDados"
_DOWNLOAD_URL = f"{_BASE}/downloadDocumento"

_DOC_TYPE_FILTERS: dict[str, tuple[str, str | None]] = {
    "relatorio_gerencial": ("Relatórios", "Relatório Gerencial"),
    "fato_relevante": ("Fato Relevante", None),
}

# Aviso aos Cotistas Estruturado — Rendimentos e Amortizações
_DIVIDEND_CAT = "Aviso aos Cotistas - Estruturado"
_DIVIDEND_TIPO = "Rendimentos e Amortizações"

_MAX_RETRIES = 4
_RETRY_DELAYS = [2, 5, 15]  # exponential-ish backoff between retries


def _parse_fnet_date(value: str) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value.strip()[:10], "%d/%m/%Y").date()
    except ValueError:
        return None


async def _post_with_retry(session: AsyncSession, payload: dict, cnpj: str) -> dict | None:
    """POST to FNET listing API with retry on network errors."""
    delays = _RETRY_DELAYS + [None]
    for attempt, wait in enumerate(delays, 1):
        try:
            r = await session.post(
                _LIST_URL,
                data=payload,
                headers={"Referer": _PAGE_URL},
                timeout=20,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if wait is not None:
                logger.warning(f"FNET tentativa {attempt}/{_MAX_RETRIES} falhou para {cnpj}: {e}. Aguardando {wait}s...")
                await asyncio.sleep(wait)
            else:
                logger.error(f"FNET esgotou {_MAX_RETRIES} tentativas para CNPJ {cnpj}: {e}")
    return None


async def fetch_fii_documents(
    cnpj: str,
    since_date: date,
    doc_types: list[str] | None = None,
) -> list[dict]:
    """
    Lists FII documents from FNET for the given CNPJ published on or after since_date.

    doc_types: list of strings from _DOC_TYPE_FILTERS keys.
               If None, fetches all supported types.

    Returns list of dicts with:
      title, document_type, published_at (ISO str), source_url (PDF download URL), raw_data ("")
    """
    if doc_types is None:
        doc_types = list(_DOC_TYPE_FILTERS.keys())

    wanted_filters = {dt: _DOC_TYPE_FILTERS[dt] for dt in doc_types if dt in _DOC_TYPE_FILTERS}
    if not wanted_filters:
        return []

    documents: list[dict] = []

    async with AsyncSession(impersonate="chrome120") as session:
        # Warm up Cloudflare cookies — best-effort, failure is non-fatal
        try:
            await session.get(_PAGE_URL, timeout=30)
        except Exception as e:
            logger.debug(f"FNET warm-up ignorado: {e}")

        start = 0
        page_size = 50

        while True:
            payload = {
                "d": "1",
                "s": str(start),
                "l": str(page_size),
                "o[0][dataReferencia]": "desc",
                "cnpj": cnpj,
                "cnpjFundo": cnpj,
                "isSession": "false",
            }

            data = await _post_with_retry(session, payload, cnpj)
            if data is None:
                break

            rows = data.get("data", [])
            if not rows:
                break

            oldest_on_page: date | None = None

            for row in rows:
                entrega_dt = _parse_fnet_date(row.get("dataEntrega", ""))
                if entrega_dt is None:
                    continue

                if oldest_on_page is None or entrega_dt < oldest_on_page:
                    oldest_on_page = entrega_dt

                if entrega_dt < since_date:
                    continue

                cat = row.get("categoriaDocumento", "")
                tipo = row.get("tipoDocumento", "")
                doc_id = row.get("id")

                matched_type: str | None = None
                for dt_name, (want_cat, want_tipo) in wanted_filters.items():
                    if cat == want_cat and (want_tipo is None or tipo == want_tipo):
                        matched_type = dt_name
                        break

                if matched_type is None or doc_id is None:
                    continue

                fund_name = row.get("descricaoFundo", "").strip()
                ref = row.get("dataReferencia", "").strip()
                label = tipo or cat
                title = f"{label} — {fund_name} ({ref})"
                pdf_url = f"{_DOWNLOAD_URL}?id={doc_id}"

                documents.append({
                    "title": title,
                    "document_type": matched_type,
                    "published_at": entrega_dt.isoformat(),
                    "source_url": pdf_url,
                    "raw_data": "",
                })

            if oldest_on_page is not None and oldest_on_page < since_date:
                break

            start += page_size
            if start >= data.get("recordsFiltered", 0):
                break

    logger.info(f"FNET {cnpj}: {len(documents)} documento(s) desde {since_date} ({doc_types})")
    return documents


async def download_pdf(url: str) -> bytes:
    """Downloads a PDF from FNET with retry on network errors."""
    async with AsyncSession(impersonate="chrome120") as session:
        try:
            await session.get(_PAGE_URL, timeout=30)
        except Exception:
            pass

        delays = _RETRY_DELAYS + [None]
        for attempt, wait in enumerate(delays, 1):
            try:
                r = await session.get(url, headers={"Referer": _PAGE_URL}, timeout=120)
                r.raise_for_status()
                return r.content
            except Exception as e:
                if wait is not None:
                    logger.warning(f"FNET download tentativa {attempt}/{_MAX_RETRIES} falhou: {e}. Aguardando {wait}s...")
                    await asyncio.sleep(wait)
                else:
                    raise


def _parse_dividend_xml(xml_bytes: bytes) -> dict | None:
    """
    Parses the structured XML from FNET 'Aviso aos Cotistas / Rendimentos e Amortizações'.
    Returns dict with: ticker, valor_por_cota, data_base (ex-date), data_pagamento, isento_ir

    XML root: DadosEconomicoFinanceiros/InformeRendimentos/Provento/Rendimento
    NOTE: ElementTree leaf elements are falsy even with text — always use `is not None`.
    """
    try:
        root = ET.fromstring(xml_bytes)
        provento = root.find("InformeRendimentos/Provento")
        if provento is None:
            return None
        rendimento = provento.find("Rendimento")
        if rendimento is None:
            return None

        def txt(tag: str) -> str:
            # Check rendimento first, then provento; use `is not None` (not truthiness)
            # because leaf ET elements are falsy even when they have text content.
            el = rendimento.find(tag)
            if el is None:
                el = provento.find(tag)
            return el.text.strip() if el is not None and el.text else ""

        ticker = (provento.findtext("CodNegociacao") or "").strip()
        valor_str = txt("ValorProvento")
        return {
            "ticker": ticker,
            "valor_por_cota": float(valor_str) if valor_str else None,
            "data_base": txt("DataBase"),        # ex-dividend date (YYYY-MM-DD)
            "data_pagamento": txt("DataPagamento"),
            "periodo": txt("PeriodoReferencia"),
            "isento_ir": txt("RendimentoIsentoIR").lower() == "sim",
        }
    except Exception as e:
        logger.debug(f"Erro ao parsear XML de dividendo FNET: {e}")
        return None


async def fetch_fii_dividends(cnpj: str, since_date: date) -> list[dict]:
    """
    Fetches structured dividend announcements (Aviso aos Cotistas) for a FII from FNET.
    Returns list of dicts: {ticker, valor_por_cota, data_base, data_pagamento, periodo, isento_ir, published_at}
    Uses curl-cffi for the listing POST (Cloudflare protected), httpx for XML download.
    """
    results: list[dict] = []
    start = 0
    page_size = 20

    async with AsyncSession(impersonate="chrome120") as session:
        # Warm up Cloudflare
        try:
            await session.get(_PAGE_URL, timeout=30)
        except Exception:
            pass

        async with httpx.AsyncClient(
            timeout=30,
            headers={"User-Agent": "Mozilla/5.0", "Referer": _PAGE_URL},
        ) as xml_client:

            while True:
                payload = {
                    "d": "1", "s": str(start), "l": str(page_size),
                    "o[0][dataReferencia]": "desc",
                    "cnpj": cnpj,
                    "cnpjFundo": cnpj,
                    "isSession": "false",
                }
                data = await _post_with_retry(session, payload, cnpj)
                if data is None:
                    break

                rows = data.get("data", [])
                if not rows:
                    break

                oldest_on_page: date | None = None
                for row in rows:
                    entrega_dt = _parse_fnet_date(row.get("dataEntrega", ""))
                    if entrega_dt is None:
                        continue
                    if oldest_on_page is None or entrega_dt < oldest_on_page:
                        oldest_on_page = entrega_dt
                    if entrega_dt < since_date:
                        continue
                    if row.get("categoriaDocumento") != _DIVIDEND_CAT:
                        continue
                    if row.get("tipoDocumento") != _DIVIDEND_TIPO:
                        continue

                    doc_id = row.get("id")
                    if not doc_id:
                        continue

                    # Download structured XML — plain httpx works (no Cloudflare on downloadDocumento)
                    try:
                        xml_r = await xml_client.get(
                            f"{_DOWNLOAD_URL}?id={doc_id}",
                            headers={"Referer": _PAGE_URL},
                        )
                        xml_r.raise_for_status()
                        dividend = _parse_dividend_xml(xml_r.content)
                        if dividend:
                            dividend["published_at"] = entrega_dt.isoformat()
                            results.append(dividend)
                    except Exception as e:
                        logger.warning(f"FNET dividend XML {doc_id} error: {e}")

                if oldest_on_page is not None and oldest_on_page < since_date:
                    break
                start += page_size
                if start >= data.get("recordsFiltered", 0):
                    break

    logger.info(f"FNET dividends {cnpj}: {len(results)} anúncio(s) desde {since_date}")
    return results
