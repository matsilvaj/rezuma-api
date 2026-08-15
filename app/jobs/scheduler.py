import asyncio
import logging
from collections import defaultdict
from datetime import date, timedelta

import httpx
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.database import get_supabase
from app.services.ai import summarize
from app.services.b3 import is_b3_assets_empty, sync_b3_assets
from app.services.cvm import download_pdf as cvm_download_pdf
from app.services.cvm import _UNSET as _UNSET_SI
from app.services.cvm import fetch_new_documents
from app.services.email import send_admin_alert, send_consolidated_report
from app.services.fnet import download_pdf as fnet_download_pdf
from app.services.statusinvest import fetch_fii_dividends as si_fetch_dividends
from app.services.statusinvest import fetch_fii_documents as si_fetch_documents
from app.services.pdf import extract_text
from app.services.telegram import send_asset_report
from app.services.tradingview import fetch_quotes

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()


def _run_async(coro) -> None:
    asyncio.run(coro)


async def _process_pipeline(days_back: int = 1) -> None:
    """
    Pipeline principal do Rezuma:
    1. Busca ativos monitorados e documentos novos na CVM
    2. Gera resumo + métricas com IA (reutiliza se já processado)
    3. Consolida por usuário e envia uma notificação por canal
    """
    since_date = date.today() - timedelta(days=days_back)
    supabase = get_supabase()

    assets_result = (
        supabase.table("assets")
        .select("ticker, b3_assets(name, cnpj, type)")
        .execute()
    )

    seen_tickers: set[str] = set()
    unique_assets = []
    for row in assets_result.data:
        ticker = row["ticker"]
        if ticker not in seen_tickers:
            seen_tickers.add(ticker)
            unique_assets.append(row)

    logger.info(f"Processando {len(unique_assets)} ativo(s) únicos desde {since_date}...")

    # Batch fetch market quotes from TradingView
    all_tickers = [a["ticker"] for a in unique_assets]
    tv_quotes = await fetch_quotes(all_tickers)

    # Fila de relatórios por usuário: {user_id: {ticker: [report_info]}}
    queue: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    # Dividend announcements per ticker: {ticker: [dividend_info]}
    dividends_map: dict[str, list[dict]] = {}

    # Rastreamento de saúde das fontes de dados
    si_none_tickers: list[str] = []   # FIIs onde Status Invest retornou None (estrutura pode ter mudado)
    cvm_error_tickers: list[str] = [] # Ações onde CVM lançou exceção
    fnet_error_tickers: list[str] = []# FIAGROs onde FNET falhou completamente
    total_fiis = sum(1 for a in unique_assets if (a.get("b3_assets") or {}).get("type") == "fii")

    for asset in unique_assets:
        ticker = asset["ticker"]
        b3_info = asset.get("b3_assets") or {}
        asset_type = b3_info.get("type", "acao")
        search_term = b3_info.get("cnpj")

        if not search_term:
            logger.warning(f"{ticker}: CNPJ não disponível no catálogo — pulando. Execute sync_b3_assets para tentar resolver.")
            continue

        # Pre-fetch Status Invest for FIIs — allows health monitoring without double-fetch
        si_docs_preloaded = _UNSET_SI
        if asset_type == "fii" and ticker:
            si_docs_preloaded = await si_fetch_documents(ticker=ticker, since_date=since_date)
            if si_docs_preloaded is None:
                si_none_tickers.append(ticker)

        try:
            documents = await fetch_new_documents(
                search_term=search_term,
                asset_type=asset_type,
                since_date=since_date,
                ticker=ticker,
                si_docs=si_docs_preloaded,
            )
        except Exception as e:
            logger.error(f"Erro ao buscar documentos para {ticker}: {e}")
            if asset_type == "acao":
                cvm_error_tickers.append(ticker)
            elif asset_type == "fiagro":
                fnet_error_tickers.append(ticker)
            continue

        # Fetch structured dividend announcements for FIIs via Status Invest
        # (bypasses FNET search/Cloudflare — uses only FNET downloadDocumento for XML)
        if asset_type == "fii" and ticker:
            try:
                fnet_since = date.today() - timedelta(days=7)
                divs = await si_fetch_dividends(
                    ticker=ticker,
                    since_date=fnet_since,
                )
                if divs:
                    dividends_map[ticker] = divs
            except Exception as e:
                logger.warning(f"Dividendos Status Invest para {ticker}: {e}")

        for doc in documents:
            try:
                # Reutiliza relatório já processado para esse documento
                existing_res = (
                    supabase.table("reports")
                    .select("id, summary, metrics")
                    .eq("ticker", ticker)
                    .eq("source_url", doc["source_url"])
                    .limit(1)
                    .execute()
                )
                existing_data = (existing_res.data or [None])[0] if existing_res else None

                pdf_bytes: bytes | None = None

                if existing_data:
                    report_id = existing_data["id"]
                    summary = existing_data["summary"]
                    logger.info(f"Relatório reutilizado: {ticker} — {doc['title']}")
                else:
                    # Busca métricas do relatório anterior para comparação
                    prev_res = (
                        supabase.table("reports")
                        .select("metrics")
                        .eq("ticker", ticker)
                        .eq("document_type", doc["document_type"])
                        .order("published_at", desc=True)
                        .limit(1)
                        .execute()
                    )
                    prev_data = (prev_res.data or [{}])[0] if prev_res else {}
                    previous_metrics = prev_data.get("metrics") or None

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

                    # Enrich with market price from TradingView for P/VP calculation
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
                        logger.warning(f"Texto vazio para {ticker} — {doc['title']}. Pulando.")
                        continue

                    summary, metrics = summarize(
                        ticker=ticker,
                        document_type=doc["document_type"],
                        text=text,
                        previous_metrics=previous_metrics,
                    )

                    if not summary:
                        continue

                    result = supabase.table("reports").insert({
                        "ticker": ticker,
                        "title": doc["title"],
                        "summary": summary,
                        "source_url": doc["source_url"],
                        "document_type": doc["document_type"],
                        "published_at": doc["published_at"],
                        "metrics": metrics or None,
                    }).execute()

                    report_id = result.data[0]["id"]
                    logger.info(f"Relatório salvo: {ticker} — {doc['title']}")

                # Descobre quais usuários têm esse ativo na carteira
                users_result = (
                    supabase.table("assets")
                    .select("user_id")
                    .eq("ticker", ticker)
                    .execute()
                )

                for row in users_result.data:
                    user_id = row["user_id"]

                    # Busca preferências do usuário separadamente
                    prof_res = (
                        supabase.table("user_profiles")
                        .select("notify_email, notify_telegram, telegram_chat_id")
                        .eq("id", user_id)
                        .limit(1)
                        .execute()
                    )
                    profile = (prof_res.data or [{}])[0] if prof_res else {}

                    # Verifica assinatura ativa
                    sub = (
                        supabase.table("subscriptions")
                        .select("status")
                        .eq("user_id", user_id)
                        .limit(1)
                        .execute()
                    )
                    sub_data = (sub.data or [{}])[0] if sub else {}
                    status = sub_data.get("status")
                    if status not in ("trialing", "active"):
                        continue

                    # Verifica se já foi notificado para não reenviar
                    already = (
                        supabase.table("notification_logs")
                        .select("id")
                        .eq("user_id", user_id)
                        .eq("report_id", report_id)
                        .execute()
                    )
                    if already.data:
                        continue

                    queue[user_id][ticker].append({
                        "report_id": report_id,
                        "title": doc["title"],
                        "summary": summary,
                        "source_url": doc["source_url"],
                        "document_type": doc["document_type"],
                        "pdf_bytes": pdf_bytes,
                        "notify_email": profile.get("notify_email", True),
                        "notify_telegram": profile.get("notify_telegram", False),
                        "telegram_chat_id": profile.get("telegram_chat_id"),
                    })

            except Exception as e:
                logger.error(f"Erro ao processar {doc.get('source_url')}: {e}")
                continue

    # Verifica saúde das fontes de dados e notifica o administrador se algo parece quebrado
    _check_data_source_health(
        si_none_tickers=si_none_tickers,
        total_fiis=total_fiis,
        cvm_error_tickers=cvm_error_tickers,
        fnet_error_tickers=fnet_error_tickers,
    )

    # Envia notificações consolidadas por usuário
    for user_id, reports_by_ticker in queue.items():
        await _notify_user(supabase, user_id, reports_by_ticker, dividends_map, tv_quotes)


def _check_data_source_health(
    si_none_tickers: list[str],
    total_fiis: int,
    cvm_error_tickers: list[str],
    fnet_error_tickers: list[str],
) -> None:
    """
    Dispara alertas por e-mail ao administrador quando uma fonte de dados parece quebrada.

    Critérios (para evitar falsos positivos):
    - Status Invest: ≥2 FIIs retornaram None E representam ≥50% dos FIIs → estrutura provavelmente mudou
    - CVM (ações): qualquer exceção inesperada → API pode ter mudado
    - FNET search (FIAGROs): qualquer exceção inesperada após todos os retries
    """
    alerts: list[str] = []

    if si_none_tickers and total_fiis >= 2:
        ratio = len(si_none_tickers) / total_fiis
        if ratio >= 0.5:
            alerts.append(
                f"Status Invest retornou None para {len(si_none_tickers)}/{total_fiis} FIIs: "
                f"{', '.join(si_none_tickers)}.\n"
                "Possível mudança na estrutura HTML do site. Verifique statusinvest.py."
            )

    if cvm_error_tickers:
        alerts.append(
            f"CVM IPE falhou para {len(cvm_error_tickers)} ação(ões): "
            f"{', '.join(cvm_error_tickers)}.\n"
            "Possível mudança na API dados.cvm.gov.br. Verifique cvm.py."
        )

    if fnet_error_tickers:
        alerts.append(
            f"FNET search falhou para {len(fnet_error_tickers)} FIAGRO(s): "
            f"{', '.join(fnet_error_tickers)}.\n"
            "Pode ser instabilidade do FNET ou Cloudflare. Monitore se persistir."
        )

    if not alerts:
        return

    body = "\n\n".join([
        "Alerta automático do pipeline Rezuma.",
        *alerts,
        f"Ciclo executado em: {date.today().isoformat()}",
    ])
    send_admin_alert(subject="Falha em fonte de dados detectada", body=body)
    logger.warning(f"Alertas de saúde disparados: {len(alerts)} problema(s)")


async def _notify_user(
    supabase,
    user_id: str,
    reports_by_ticker: dict[str, list[dict]],
    dividends_map: dict[str, list[dict]] | None = None,
    tv_quotes: dict[str, dict] | None = None,
) -> None:
    """
    Envia notificações consolidadas para um usuário:
    - E-mail: um único e-mail com todos os relatórios do dia
    - Telegram: uma mensagem por ativo
    """
    # Busca e-mail e nome do usuário
    user_auth = supabase.auth.admin.get_user_by_id(user_id)
    email = user_auth.user.email if user_auth and user_auth.user else None

    prof_res = (
        supabase.table("user_profiles")
        .select("full_name")
        .eq("id", user_id)
        .limit(1)
        .execute()
    )
    user_name = ((prof_res.data or [{}])[0] if prof_res else {}).get("full_name")

    # Determina canais a partir do primeiro relatório de qualquer ativo
    first_reports = next(iter(reports_by_ticker.values()))
    notify_email = first_reports[0].get("notify_email", True)
    notify_telegram = first_reports[0].get("notify_telegram", False)
    telegram_chat_id = first_reports[0].get("telegram_chat_id")

    report_ids = [r["report_id"] for reports in reports_by_ticker.values() for r in reports]

    # E-mail consolidado com todos os ativos
    if notify_email and email:
        reports_for_email = {
            ticker: [{"title": r["title"], "summary": r["summary"], "source_url": r["source_url"]} for r in reports]
            for ticker, reports in reports_by_ticker.items()
        }
        # Collect all downloaded PDFs as attachments
        attachments: list[dict] = []
        for ticker, reports in reports_by_ticker.items():
            for r in reports:
                if r.get("pdf_bytes"):
                    safe_title = r["title"][:40].replace("/", "-").replace(" ", "_")
                    filename = f"{ticker}_{r['document_type']}_{safe_title}.pdf"
                    attachments.append({"filename": filename, "content": r["pdf_bytes"]})

        success = send_consolidated_report(
            to_email=email,
            reports_by_ticker=reports_for_email,
            user_name=user_name,
            attachments=attachments or None,
            dividends_map=dividends_map,
            tv_quotes=tv_quotes,
        )
        for report_id in report_ids:
            _log_notification(supabase, user_id, report_id, "email", success)

    # Telegram: uma mensagem por ativo
    if notify_telegram and telegram_chat_id:
        for ticker, reports in reports_by_ticker.items():
            telegram_reports = [
                {"title": r["title"], "summary": r["summary"], "source_url": r["source_url"]}
                for r in reports
            ]
            success = await send_asset_report(
                chat_id=telegram_chat_id,
                ticker=ticker,
                reports=telegram_reports,
            )
            for r in reports:
                _log_notification(supabase, user_id, r["report_id"], "telegram", success)


def _log_notification(supabase, user_id: str, report_id: str, channel: str, success: bool) -> None:
    supabase.table("notification_logs").insert({
        "user_id": user_id,
        "report_id": report_id,
        "channel": channel,
        "status": "sent" if success else "failed",
    }).execute()


def job_fetch_and_process_reports() -> None:
    logger.info("Job: iniciando pipeline de relatórios...")
    _run_async(_process_pipeline(days_back=7))
    logger.info("Job: pipeline concluído.")


def job_sync_b3_assets() -> None:
    logger.info("Job semanal: atualizando catálogo de ativos da B3...")
    _run_async(sync_b3_assets())


async def seed_if_empty() -> None:
    try:
        if await is_b3_assets_empty():
            logger.info("Catálogo vazio — executando seed inicial...")
            await sync_b3_assets()
    except Exception as e:
        logger.error(f"Falha no seed inicial: {e}. O servidor continuará normalmente.")


def start_scheduler() -> None:
    # Rodada matinal — pega relatórios publicados durante a madrugada
    scheduler.add_job(
        job_fetch_and_process_reports,
        trigger=CronTrigger(hour=8, minute=0, timezone="America/Sao_Paulo"),
        id="fetch_reports_morning",
        replace_existing=True,
    )

    # Rodada vespertina — pega relatórios publicados durante o dia
    scheduler.add_job(
        job_fetch_and_process_reports,
        trigger=CronTrigger(hour=18, minute=0, timezone="America/Sao_Paulo"),
        id="fetch_reports_evening",
        replace_existing=True,
    )

    # Sincronização semanal do catálogo B3
    scheduler.add_job(
        job_sync_b3_assets,
        trigger=CronTrigger(day_of_week="sun", hour=3, minute=0, timezone="America/Sao_Paulo"),
        id="sync_b3_assets",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("Scheduler iniciado (8h, 18h e dom 3h).")


def stop_scheduler() -> None:
    scheduler.shutdown(wait=False)
    logger.info("Scheduler encerrado.")
