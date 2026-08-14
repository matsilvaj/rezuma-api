"""
Roda o pipeline do Summai para um único ticker específico.

Uso (da pasta summai-api):
    python -m scripts.run_single_ticker HGLG11
    python -m scripts.run_single_ticker HGLG11 --days 30
"""
import asyncio
import argparse
import logging
from collections import defaultdict
from datetime import date, timedelta

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s — %(message)s")
logger = logging.getLogger("run_single")


async def run(ticker: str, days_back: int) -> None:
    # Importações depois do logging para não poluir a saída de ajuda
    from app.core.database import get_supabase
    from app.services.ai import summarize
    from app.services.cvm import download_pdf as cvm_download_pdf
    from app.services.cvm import _UNSET as _UNSET_SI
    from app.services.cvm import fetch_new_documents
    from app.services.email import send_consolidated_report
    from app.services.fnet import download_pdf as fnet_download_pdf
    from app.services.statusinvest import fetch_fii_dividends as si_fetch_dividends
    from app.services.statusinvest import fetch_fii_documents as si_fetch_documents
    from app.services.pdf import extract_text
    from app.services.tradingview import fetch_quotes

    since_date = date.today() - timedelta(days=days_back)
    supabase = get_supabase()

    # Busca info do ativo no catálogo B3
    asset_row = (
        supabase.table("b3_assets")
        .select("ticker, name, cnpj, type")
        .eq("ticker", ticker.upper())
        .single()
        .execute()
    )
    if not asset_row.data:
        logger.error(f"Ticker {ticker} não encontrado no catálogo B3.")
        return

    b3 = asset_row.data
    asset_type = b3.get("type", "acao")
    search_term = b3.get("cnpj")

    if not search_term:
        logger.error(f"{ticker}: CNPJ não disponível no catálogo.")
        return

    logger.info(f"Processando {ticker} ({asset_type}) desde {since_date}...")

    tv_quotes = await fetch_quotes([ticker])

    si_docs_preloaded = _UNSET_SI
    if asset_type == "fii":
        si_docs_preloaded = await si_fetch_documents(ticker=ticker, since_date=since_date)
        logger.info(f"Status Invest: {len(si_docs_preloaded or [])} doc(s) encontrado(s)")

    documents = await fetch_new_documents(
        search_term=search_term,
        asset_type=asset_type,
        since_date=since_date,
        ticker=ticker,
        si_docs=si_docs_preloaded,
    )
    logger.info(f"{len(documents)} documento(s) a processar")

    dividends_map: dict[str, list[dict]] = {}
    if asset_type == "fii":
        try:
            divs = await si_fetch_dividends(ticker=ticker, since_date=date.today() - timedelta(days=7))
            if divs:
                dividends_map[ticker] = divs
                logger.info(f"Dividendos encontrados: {len(divs)}")
        except Exception as e:
            logger.warning(f"Dividendos: {e}")

    reports_for_user: list[dict] = []

    for doc in documents:
        logger.info(f"→ {doc['title'][:60]}")

        existing = (
            supabase.table("reports")
            .select("id, summary")
            .eq("ticker", ticker)
            .eq("source_url", doc["source_url"])
            .limit(1)
            .execute()
        )
        existing_data = (existing.data or [None])[0]

        if existing_data:
            logger.info("  (relatório já existe no banco — reutilizando)")
            summary = existing_data["summary"]
            pdf_bytes = None
        else:
            pdf_bytes = None
            if doc.get("raw_data"):
                text = doc["raw_data"]
            elif doc.get("source_url"):
                url = doc["source_url"]
                if "fnet.bmfbovespa.com.br" in url:
                    pdf_bytes = await fnet_download_pdf(url)
                else:
                    pdf_bytes = await cvm_download_pdf(url)
                text = extract_text(pdf_bytes) if pdf_bytes else ""
            else:
                text = ""

            if doc.get("document_type") in ("relatorio_gerencial", "informe_mensal", "apresentacao_resultados", "itr", "dfp"):
                quote = tv_quotes.get(ticker, {})
                price = quote.get("price")
                dy = quote.get("dy_anual") or quote.get("dy_atual")
                if price:
                    enrichment = f"Preço de mercado atual (TradingView): R$ {price:.2f}"
                    if dy:
                        enrichment += f" | DY anual de mercado: {dy:.2f}%"
                    text = enrichment + "\n\n" + text

            if not text:
                logger.warning("  Texto vazio — pulando.")
                continue

            prev_res = (
                supabase.table("reports")
                .select("metrics")
                .eq("ticker", ticker)
                .eq("document_type", doc["document_type"])
                .order("published_at", desc=True)
                .limit(1)
                .execute()
            )
            prev_data = (prev_res.data or [{}])[0]
            previous_metrics = prev_data.get("metrics") or None

            summary, metrics = summarize(
                ticker=ticker,
                document_type=doc["document_type"],
                text=text,
                previous_metrics=previous_metrics,
            )
            if not summary:
                continue

            supabase.table("reports").insert({
                "ticker": ticker,
                "title": doc["title"],
                "summary": summary,
                "source_url": doc["source_url"],
                "document_type": doc["document_type"],
                "published_at": doc["published_at"],
                "metrics": metrics or None,
            }).execute()
            logger.info("  Relatório salvo no banco.")

        reports_for_user.append({
            "title": doc["title"],
            "summary": summary,
            "source_url": doc["source_url"],
            "document_type": doc["document_type"],
            "pdf_bytes": pdf_bytes,
        })

    if not reports_for_user:
        logger.info("Nenhum relatório novo para enviar.")
        return

    # Busca user_ids que têm esse ticker na carteira
    assets_result = (
        supabase.table("assets")
        .select("user_id")
        .eq("ticker", ticker)
        .execute()
    )
    user_ids = [row["user_id"] for row in assets_result.data or []]

    if not user_ids:
        logger.info("Nenhum usuário com esse ativo na carteira.")
        return

    # Busca perfis
    profiles_result = (
        supabase.table("user_profiles")
        .select("id, full_name, notify_email")
        .in_("id", user_ids)
        .execute()
    )
    profiles_map = {p["id"]: p for p in profiles_result.data or []}

    attachments = [
        {
            "filename": f"{ticker}_{r['document_type']}_{r['title'][:40].replace('/', '-').replace(' ', '_')}.pdf",
            "content": r["pdf_bytes"],
        }
        for r in reports_for_user
        if r.get("pdf_bytes")
    ]

    for user_id in user_ids:
        profile = profiles_map.get(user_id, {})
        full_name = profile.get("full_name")
        notify_email = profile.get("notify_email", True)

        user_auth = supabase.auth.admin.get_user_by_id(user_id)
        to_email = user_auth.user.email if user_auth and user_auth.user else None

        if to_email and notify_email:
            ok = send_consolidated_report(
                to_email=to_email,
                reports_by_ticker={ticker: reports_for_user},
                user_name=full_name,
                attachments=attachments or None,
                dividends_map=dividends_map,
                tv_quotes=tv_quotes,
            )
            logger.info(f"E-mail {'enviado' if ok else 'FALHOU'} para {to_email}")

    logger.info("Concluído.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pipeline Summai para um único ticker")
    parser.add_argument("ticker", help="Ticker do ativo (ex: HGLG11, BBAS3)")
    parser.add_argument("--days", type=int, default=60, help="Quantos dias atrás buscar (padrão: 60)")
    args = parser.parse_args()

    asyncio.run(run(ticker=args.ticker.upper(), days_back=args.days))
