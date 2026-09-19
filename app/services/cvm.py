"""
CVM data fetcher using dados.cvm.gov.br bulk CSV downloads.

FII: Relatório Gerencial + Fato Relevante → FNET PDFs (primary)
     Informe Mensal → CVM CSV (fallback / supplementary)
CIA_ABERTA: ITR/DFP/Fato Relevante → IPE index CSV with LINK_DOC to PDFs

Documents returned include:
  source_url: PDF URL or dedup key for CSV-based docs
  raw_data:   pre-formatted text (empty for PDF docs)
"""
import csv
import io
import logging
import zipfile
from datetime import date, timedelta

import httpx

from app.services.fnet import fetch_fii_documents as _fnet_fetch
from app.services.statusinvest import fetch_fii_documents as _si_fetch

logger = logging.getLogger(__name__)

_BASE_URL = "https://dados.cvm.gov.br/dados"

# Maps doc_type → list of (CATEGORIA_UPPER, TIPO_substr_upper_or_None).
# categoria is matched case-insensitively; tipo_substr (if set) must appear in Tipo.upper().
_IPE_CATEGORY_MAP: dict[str, list[tuple[str, str | None]]] = {
    "itr": [("ITR", None)],
    "dfp": [("DFP", None)],
    "fato_relevante": [("FATO RELEVANTE", None)],
    # Earnings releases: financial press-releases + investor presentations alongside results
    "apresentacao_resultados": [
        ("DADOS ECONÔMICO-FINANCEIROS", None),
        ("COMUNICADO AO MERCADO", "APRESENTAÇÕES"),
    ],
}

_ACAO_DOC_TYPES = list(_IPE_CATEGORY_MAP.keys())


# ── helpers ───────────────────────────────────────────────────────────────────


def _normalize_cnpj(cnpj: str) -> str:
    return "".join(c for c in (cnpj or "") if c.isdigit())


async def _download_bytes(url: str) -> bytes:
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
        r = await client.get(url, headers={"User-Agent": "Rezuma/1.0"})
        r.raise_for_status()
        return r.content


def _read_csv_from_zip(zip_bytes: bytes, name_hint: str = "") -> tuple[list[dict], list[str]]:
    """
    Returns (rows, csv_filenames).
    If name_hint is given, reads the first CSV whose name contains that hint.
    CVM uses latin-1 encoding and semicolon delimiters.
    """
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        csv_names = sorted(n for n in zf.namelist() if n.lower().endswith(".csv"))
        if not csv_names:
            logger.warning("Nenhum CSV encontrado no ZIP.")
            return [], []
        target = csv_names[0]
        if name_hint:
            matches = [n for n in csv_names if name_hint in n.lower()]
            if matches:
                target = matches[0]
        with zf.open(target) as f:
            text = f.read().decode("latin-1")
    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    return list(reader), csv_names


def _read_all_csvs_from_zip(zip_bytes: bytes) -> dict[str, list[dict]]:
    """Read ALL CSVs from a ZIP, keyed by filename."""
    result: dict[str, list[dict]] = {}
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        csv_names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        for name in csv_names:
            with zf.open(name) as f:
                text = f.read().decode("latin-1")
            reader = csv.DictReader(io.StringIO(text), delimiter=";")
            result[name] = list(reader)
    return result


def _parse_date(value: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


# ── FII informe mensal ────────────────────────────────────────────────────────


_FII_INF_MENSAL_FIELDS = {
    # geral CSV
    "Nome_Fundo_Classe": "Nome do Fundo",
    "CNPJ_Fundo_Classe": "CNPJ",
    "Data_Referencia": "Competência",
    "Segmento_Atuacao": "Segmento",
    "Tipo_Gestao": "Tipo de Gestão",
    # complemento CSV, métricas-chave para o investidor
    "Valor_Patrimonial_Cotas": "Valor patrimonial da cota (R$)",
    "Patrimonio_Liquido": "Patrimônio Líquido (R$)",
    "Valor_Ativo": "Ativo Total (R$)",
    "Cotas_Emitidas": "Cotas emitidas",
    "Total_Numero_Cotistas": "Total de cotistas",
    "Numero_Cotistas_Pessoa_Fisica": "Cotistas pessoa física",
    "Percentual_Dividend_Yield_Mes": "Dividend Yield do mês (decimal, ex: 0.015 = 1.5%)",
    "Percentual_Rentabilidade_Efetiva_Mes": "Rentabilidade efetiva do mês (decimal)",
    "Percentual_Rentabilidade_Patrimonial_Mes": "Rentabilidade patrimonial do mês (decimal)",
    "Percentual_Despesas_Taxa_Administracao": "Taxa de administração mensal (decimal)",
    # ativo_passivo CSV
    "Rendimentos_Distribuir": "Rendimentos a distribuir no mês (R$)",
    "Imoveis_Renda_Acabados": "Imóveis de renda prontos (R$)",
    "Imoveis_Renda_Construcao": "Imóveis em construção (R$)",
    "FII": "Investido em outros FIIs (R$)",
    "CRI_CRA": "Investido em CRI/CRA (R$)",
    "Total_Passivo": "Total Passivo / Dívidas (R$)",
    "Obrigacoes_Securitizacao_Recebiveis": "Dívida securitizada (R$)",
    "Contas_Receber_Aluguel": "Aluguéis a receber (R$)",
}


def _format_fii_row(row: dict) -> str:
    lines: list[str] = []
    known: set[str] = set(_FII_INF_MENSAL_FIELDS.keys())

    for key, label in _FII_INF_MENSAL_FIELDS.items():
        val = row.get(key, "").strip()
        if val:
            lines.append(f"{label}: {val}")

    # Derived field: rendimento por cota (total a distribuir ÷ cotas)
    try:
        rendimentos = float(row.get("Rendimentos_Distribuir", "") or 0)
        cotas = float(row.get("Cotas_Emitidas", "") or row.get("Quantidade_Cotas_Emitidas", "") or 0)
        if rendimentos > 0 and cotas > 0:
            rend_por_cota = rendimentos / cotas
            lines.append(f"Rendimento estimado por cota no mês (R$): {rend_por_cota:.4f}")
    except (ValueError, ZeroDivisionError):
        pass

    # Derived field: DY anualizado
    try:
        dy_mes = float(row.get("Percentual_Dividend_Yield_Mes", "") or 0)
        if dy_mes > 0:
            lines.append(f"Dividend Yield anualizado estimado (%): {dy_mes * 12 * 100:.2f}")
    except ValueError:
        pass

    # Remaining unmapped fields (pass-through for AI context)
    skip = {"Versao", "Tipo_Fundo_Classe", "Codigo_ISIN", "Fundo_Exclusivo",
            "Cotistas_Vinculo_Familiar", "Mandato", "Prazo_Duracao", "Data_Prazo_Duracao",
            "Encerramento_Exercicio_Social", "Mercado_Negociacao_Bolsa",
            "Mercado_Negociacao_MBO", "Mercado_Negociacao_MB",
            "Entidade_Administradora_BVMF", "Entidade_Administradora_CETIP",
            "Nome_Administrador", "CNPJ_Administrador", "Logradouro", "Numero",
            "Complemento", "Bairro", "Cidade", "Estado", "CEP",
            "Telefone1", "Telefone2", "Telefone3", "Site", "Email",
            "Data_Entrega", "Data_Funcionamento", "Data_Informacao_Numero_Cotistas",
            "Quantidade_Cotas_Emitidas", "Publico_Alvo",
            "CNPJ_Fundo_Classe", "Data_Referencia", "Nome_Fundo_Classe"}

    for k, v in row.items():
        if k not in known and k not in skip and v and v.strip():
            lines.append(f"{k}: {v.strip()}")

    return "\n".join(lines)


async def _fetch_fii_inf_mensal(cnpj: str, since_date: date) -> list[dict]:
    year = date.today().year
    url = f"{_BASE_URL}/FII/doc/inf_mensal/DADOS/inf_mensal_fii_{year}.zip"
    try:
        zip_bytes = await _download_bytes(url)
    except httpx.HTTPError as e:
        logger.error(f"Erro ao baixar inf_mensal FII {year}: {e}")
        return []

    all_csvs = _read_all_csvs_from_zip(zip_bytes)
    logger.info(f"inf_mensal FII {year}: CSVs encontrados: {list(all_csvs.keys())}")

    cnpj_digits = _normalize_cnpj(cnpj)

    # Build lookup tables keyed by (cnpj_digits, date_str) for merging CSVs
    def index_by_cnpj_date(rows: list[dict]) -> dict[tuple, dict]:
        idx: dict[tuple, dict] = {}
        for row in rows:
            k = (_normalize_cnpj(row.get("CNPJ_Fundo_Classe", "")), row.get("Data_Referencia", "")[:10])
            idx[k] = row
        return idx

    indexed: dict[str, dict[tuple, dict]] = {
        name: index_by_cnpj_date(rows) for name, rows in all_csvs.items()
    }

    # Use the 'geral' CSV as primary (has fund names)
    geral_key = next((k for k in all_csvs if "geral" in k.lower()), next(iter(all_csvs), ""))
    geral_rows = all_csvs.get(geral_key, [])

    documents: list[dict] = []
    for row in geral_rows:
        row_cnpj = _normalize_cnpj(row.get("CNPJ_Fundo_Classe", ""))
        if row_cnpj != cnpj_digits:
            continue

        dt = _parse_date(row.get("Data_Referencia", ""))
        if dt is None or dt < since_date:
            continue

        # Merge data from all CSVs for this CNPJ+date
        merged: dict = dict(row)
        key = (row_cnpj, dt.isoformat())
        for name, idx in indexed.items():
            if name != geral_key and key in idx:
                merged.update({k: v for k, v in idx[key].items() if k not in merged or not merged[k]})

        fund_name = merged.get("Nome_Fundo_Classe", cnpj).strip()
        raw_text = f"INFORME MENSAL FII, {fund_name}\n" + _format_fii_row(merged)

        dedup_url = f"dados.cvm.gov.br/FII/inf_mensal/{cnpj_digits}/{dt.strftime('%Y-%m')}"
        documents.append({
            "title": f"Informe Mensal, {fund_name} ({dt.strftime('%m/%Y')})",
            "document_type": "informe_mensal",
            "published_at": dt.isoformat(),
            "source_url": dedup_url,
            "raw_data": raw_text,
        })

    return documents


# ── CIA_ABERTA via IPE ────────────────────────────────────────────────────────


async def _fetch_cia_via_ipe(
    cnpj: str,
    since_date: date,
    doc_types: list[str],
) -> list[dict]:
    year = date.today().year
    url = f"{_BASE_URL}/CIA_ABERTA/doc/IPE/DADOS/ipe_cia_aberta_{year}.zip"
    try:
        zip_bytes = await _download_bytes(url)
    except httpx.HTTPError as e:
        logger.error(f"Erro ao baixar IPE CIA_ABERTA {year}: {e}")
        return []

    rows, csv_names = _read_csv_from_zip(zip_bytes)
    logger.info(f"IPE CIA_ABERTA {year}: {len(rows)} linhas, arquivos: {csv_names}")

    cnpj_digits = _normalize_cnpj(cnpj)
    documents: list[dict] = []

    for row in rows:
        # IPE CSV uses CamelCase column names (as of 2024+)
        row_cnpj = _normalize_cnpj(row.get("CNPJ_Companhia", ""))
        if row_cnpj != cnpj_digits:
            continue

        categ_raw = (row.get("Categoria") or "").strip()
        categ_u = categ_raw.upper()
        tipo_raw = (row.get("Tipo") or "").strip()
        tipo_u = tipo_raw.upper()

        dt = _parse_date(row.get("Data_Entrega") or row.get("Data_Referencia", ""))
        if dt is None or dt < since_date:
            continue

        link = (row.get("Link_Download") or "").strip()
        if not link:
            continue

        # Match against _IPE_CATEGORY_MAP rules
        matched_type: str | None = None
        for dt_name, rules in _IPE_CATEGORY_MAP.items():
            if dt_name not in doc_types:
                continue
            for cat_u, tipo_substr in rules:
                if categ_u != cat_u:
                    continue
                if tipo_substr is not None and tipo_substr not in tipo_u:
                    continue
                matched_type = dt_name
                break
            if matched_type:
                break

        if matched_type is None:
            continue

        assunto = (row.get("Assunto") or "").strip()
        title = assunto or tipo_raw or categ_raw

        documents.append({
            "title": title or f"{categ_raw}, {dt.isoformat()}",
            "document_type": matched_type,
            "published_at": dt.isoformat(),
            "source_url": link,
            "raw_data": "",  # PDF, will be downloaded by scheduler
        })

    return documents


# ── public API ────────────────────────────────────────────────────────────────


_UNSET = object()  # sentinel: caller did not pre-fetch SI docs


async def fetch_new_documents(
    search_term: str,
    asset_type: str,
    since_date: date | None = None,
    ticker: str | None = None,
    si_docs=_UNSET,
) -> list[dict]:
    """
    Busca documentos recentes para um ativo.
    search_term deve ser o CNPJ do fundo/empresa (com ou sem formatação).
    ticker é usado para FIIs: tenta Status Invest (estável) antes do FNET (instável).

    si_docs, resultado pré-carregado de statusinvest.fetch_fii_documents:
      _UNSET      → não pre-carregado, busca internamente
      None        → ticker não encontrado no SI → aciona fallback FNET
      []          → encontrado, sem docs no período → não aciona FNET
      [...]       → docs encontrados, usa direto

    Retorna lista de dicts com: title, document_type, published_at,
    source_url (URL do PDF ou chave de dedup), raw_data (texto se CSV).
    """
    if since_date is None:
        since_date = date.today() - timedelta(days=1)

    documents: list[dict] = []

    if asset_type == "fii":
        # Resolve SI docs, use pre-loaded if provided, otherwise fetch now
        if si_docs is _UNSET:
            resolved_si = await _si_fetch(ticker=ticker, since_date=since_date) if ticker else None
        else:
            resolved_si = si_docs  # None | [] | [...]

        if resolved_si is not None:
            documents.extend(resolved_si)
        else:
            fnet_docs = await _fnet_fetch(
                cnpj=search_term,
                since_date=since_date,
                doc_types=["relatorio_gerencial", "fato_relevante"],
            )
            documents.extend(fnet_docs)

        # Supplementary: informe mensal estruturado da CVM (CSV), não duplica pois
        # usa source_url diferente (dados.cvm.gov.br vs fnet.bmfbovespa.com.br)
        inf_docs = await _fetch_fii_inf_mensal(cnpj=search_term, since_date=since_date)
        documents.extend(inf_docs)

    elif asset_type == "acao":
        docs = await _fetch_cia_via_ipe(
            cnpj=search_term,
            since_date=since_date,
            doc_types=_ACAO_DOC_TYPES,
        )
        documents.extend(docs)

    logger.info(
        f"'{search_term}' ({asset_type}): {len(documents)} documento(s) desde {since_date}."
    )
    return documents


async def download_pdf(url: str) -> bytes:
    """Faz download de um documento PDF da CVM pelo LINK_DOC."""
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        r = await client.get(url, headers={"User-Agent": "Rezuma/1.0"})
        r.raise_for_status()
        return r.content
