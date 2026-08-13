from fastapi import APIRouter, Depends, Query

from app.core.database import get_supabase
from app.core.security import get_user_id

router = APIRouter()


@router.get("/")
def list_reports(
    user_id: str = Depends(get_user_id),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
):
    """
    Retorna os relatórios resumidos dos ativos da carteira do usuário,
    ordenados do mais recente para o mais antigo, com paginação.
    """
    supabase = get_supabase()

    # Busca os tickers do usuário para filtrar os relatórios
    assets_result = (
        supabase.table("assets")
        .select("ticker")
        .eq("user_id", user_id)
        .execute()
    )

    if not assets_result.data:
        return {"reports": [], "page": page, "total": 0}

    tickers = [a["ticker"] for a in assets_result.data]
    offset = (page - 1) * limit

    # Busca relatórios apenas dos tickers da carteira do usuário
    reports_result = (
        supabase.table("reports")
        .select("id, ticker, title, summary, document_type, source_url, published_at, created_at", count="exact")
        .in_("ticker", tickers)
        .order("published_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )

    return {
        "reports": reports_result.data,
        "page": page,
        "total": reports_result.count or 0,
    }
