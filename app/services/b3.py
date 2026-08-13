import base64
import csv
import io
import json
import logging
import re
import zipfile

import httpx

from app.core.database import get_supabase

logger = logging.getLogger(__name__)

_BRAPI_LIST_URL = "https://brapi.dev/api/quote/list"
_BRAPI_PAGE_SIZE = 100

# Subtipos brapi relevantes para o investidor comum brasileiro
# fi-agro = FIAGROs, fi-infra = Fundos de Infraestrutura — mesma estrutura dos FIIs
_VALID_SUBTYPES = {"stock", "unit", "fii", "fi-agro", "fi-infra"}

# Subtipos que operam como FII (FNET + CVM inf_mensal, dividendos mensais)
_FII_LIKE_SUBTYPES = {"fii", "fi-agro", "fi-infra"}

_FRACTIONAL_RE = re.compile(r"^[A-Z]{4}\d+F$")

# B3 official companies endpoint (ações)
_B3_COMPANIES_URL = "https://sistemaswebb3-listados.b3.com.br/listedCompaniesProxy/CompanyCall/GetInitialCompanies/{payload}"
_B3_PAGE_SIZE = 120

# CVM inf_mensal FII (FIIs) — has CNPJ + ISIN per fund
_CVM_INF_MENSAL_FII = "https://dados.cvm.gov.br/dados/FII/doc/inf_mensal/DADOS/inf_mensal_fii_{year}.zip"

_B3_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Origin": "https://www.b3.com.br",
    "Referer": "https://www.b3.com.br/",
}


def _b3_payload(obj: dict) -> str:
    return base64.b64encode(json.dumps(obj).encode()).decode()


def _normalize_cnpj(cnpj: str) -> str:
    digits = "".join(c for c in (cnpj or "") if c.isdigit())
    # CNPJ always has 14 digits — zero-pad if leading zeros were stripped (e.g. BBAS3)
    return digits.zfill(14) if digits else ""


async def _fetch_acao_cnpj_map(client: httpx.AsyncClient) -> dict[str, str]:
    """
    Fetches all listed companies from B3 official API.
    Returns {issuingCompany_upper (4 chars): cnpj_digits} for stocks.
    """
    cnpj_map: dict[str, str] = {}
    page = 1

    while True:
        payload = _b3_payload({"language": "pt-br", "pageNumber": page, "pageSize": _B3_PAGE_SIZE})
        url = _B3_COMPANIES_URL.format(payload=payload)
        try:
            r = await client.get(url, headers=_B3_HEADERS, timeout=15)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            logger.warning(f"B3 companies pág {page}: {e}")
            break

        results = data.get("results", [])
        for item in results:
            issuing = (item.get("issuingCompany") or "").strip().upper()
            cnpj = _normalize_cnpj(item.get("cnpj", ""))
            if issuing and len(cnpj) == 14:
                cnpj_map[issuing] = cnpj

        total_pages = data.get("page", {}).get("totalPages", 1)
        if page >= total_pages:
            break
        page += 1

    logger.info(f"B3 companies: {len(cnpj_map)} empresas com CNPJ.")
    return cnpj_map


def _parse_fii_cnpj_from_zip(zip_bytes: bytes, cnpj_map: dict, ticker_date: dict) -> None:
    """Parses a single inf_mensal FII ZIP, updating cnpj_map in place."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        geral = next((n for n in zf.namelist() if "geral" in n.lower() and n.endswith(".csv")), None)
        if not geral:
            return
        with zf.open(geral) as f:
            text = f.read().decode("latin-1")

    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    for row in reader:
        cnpj = _normalize_cnpj(row.get("CNPJ_Fundo_Classe", ""))
        isin = (row.get("Codigo_ISIN") or "").strip()
        ref_date = (row.get("Data_Referencia") or "").strip()
        if len(cnpj) != 14:
            continue
        # Derive ticker: ISIN chars 2-6 = fund code + "11" suffix (standard FII pattern)
        if isin.startswith("BR") and len(isin) >= 6:
            ticker = isin[2:6].upper() + "11"
            # Keep the entry with the latest reference date to resolve ISIN prefix collisions
            if ticker not in cnpj_map or ref_date > ticker_date.get(ticker, ""):
                cnpj_map[ticker] = cnpj
                ticker_date[ticker] = ref_date


async def _fetch_fii_cnpj_map(client: httpx.AsyncClient) -> dict[str, str]:
    """
    Fetches FII CNPJ mapping from CVM inf_mensal_fii_geral CSV.
    Tries current year first, falls back to previous two years to catch
    newer FIIs not yet in the current year's data.
    Returns {ticker_upper: cnpj_digits} with validated 14-digit CNPJs only.
    """
    from datetime import date
    current_year = date.today().year
    years = [current_year, current_year - 1, current_year - 2]

    cnpj_map: dict[str, str] = {}
    ticker_date: dict[str, str] = {}

    for year in years:
        url = _CVM_INF_MENSAL_FII.format(year=year)
        try:
            r = await client.get(url, headers={"User-Agent": "Summai/1.0"}, timeout=60)
            r.raise_for_status()
            _parse_fii_cnpj_from_zip(r.content, cnpj_map, ticker_date)
            logger.info(f"CVM inf_mensal FII {year}: {len(cnpj_map)} FIIs acumulados.")
        except Exception as e:
            logger.warning(f"CVM inf_mensal FII {year}: {e}")

    return cnpj_map


async def _fetch_all_assets() -> list[dict]:
    """
    Fetches all B3 assets from brapi.dev (ticker + name + type),
    then enriches each with CNPJ from official sources:
      - Stocks: B3 GetInitialCompanies API (issuingCompany → CNPJ)
      - FIIs:   CVM inf_mensal_fii_geral (ISIN → ticker → CNPJ)
    """
    all_assets: list[dict] = []

    async with httpx.AsyncClient(timeout=30) as client:
        # Step 1: fetch ticker list from brapi
        response = await client.get(_BRAPI_LIST_URL, params={"limit": _BRAPI_PAGE_SIZE, "page": 1})
        response.raise_for_status()
        data = response.json()
        total_pages = data.get("totalPages", 1)
        all_pages = [data]
        for page in range(2, total_pages + 1):
            resp = await client.get(_BRAPI_LIST_URL, params={"limit": _BRAPI_PAGE_SIZE, "page": page})
            resp.raise_for_status()
            all_pages.append(resp.json())

        # Step 2: fetch CNPJ maps from official sources in parallel
        acao_cnpj, fii_cnpj = await _fetch_acao_cnpj_map(client), await _fetch_fii_cnpj_map(client)

    for page_data in all_pages:
        for item in page_data.get("stocks", []):
            sub_type = item.get("subType", "")
            if sub_type not in _VALID_SUBTYPES:
                continue

            ticker = item.get("stock", "").strip().upper()
            name = item.get("name", "").strip()
            if not ticker or not name:
                continue
            if _FRACTIONAL_RE.match(ticker):
                continue

            normalized_type = "fii" if sub_type in _FII_LIKE_SUBTYPES else "acao"

            # Resolve CNPJ from official source
            if normalized_type == "fii":
                cnpj = fii_cnpj.get(ticker)
            else:
                # Stocks: first 4 chars of ticker = issuingCompany (PETR4 → PETR)
                cnpj = acao_cnpj.get(ticker[:4].upper())

            all_assets.append({
                "ticker": ticker,
                "name": name,
                "type": normalized_type,
                "cnpj": cnpj,  # None if not found in official sources
            })

    found = sum(1 for a in all_assets if a["cnpj"])
    logger.info(f"{len(all_assets)} ativos, {found} com CNPJ resolvido.")
    return all_assets


async def sync_b3_assets() -> None:
    """
    Sincroniza o catálogo completo de ativos da B3 (ações + FIIs) no banco.
    CNPJ populado automaticamente via B3 oficial (ações) e CVM (FIIs).
    """
    logger.info("Iniciando sincronização do catálogo de ativos da B3...")

    assets = await _fetch_all_assets()
    if not assets:
        logger.warning("Nenhum ativo retornado — sincronização abortada.")
        return

    supabase = get_supabase()
    batch_size = 500
    for i in range(0, len(assets), batch_size):
        batch = assets[i: i + batch_size]
        supabase.table("b3_assets").upsert(batch, on_conflict="ticker").execute()

    logger.info(f"Catálogo sincronizado: {len(assets)} ativos.")


async def is_b3_assets_empty() -> bool:
    supabase = get_supabase()
    result = supabase.table("b3_assets").select("ticker").limit(1).execute()
    return len(result.data) == 0
