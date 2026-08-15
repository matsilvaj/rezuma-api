import re

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.core.database import get_supabase
from app.core.rate_limit import is_rate_limited
from app.core.security import get_user_id
from app.models.schemas import AssetCreate

router = APIRouter()

_SEARCH_ALLOWED = re.compile(r"^[A-Za-z0-9 ]+$")


@router.get("/search")
def search_b3_assets(request: Request, q: str = Query(min_length=1, max_length=20)):
    """
    Busca ativos no catálogo da B3 pelo ticker ou nome.
    Endpoint público para autocomplete — não exige autenticação.
    """
    forwarded = request.headers.get("X-Forwarded-For")
    ip = forwarded.split(",")[-1].strip() if forwarded else (request.client.host if request.client else "unknown")
    if is_rate_limited(ip):
        raise HTTPException(status_code=429, detail="Too many requests.")

    if not _SEARCH_ALLOWED.match(q):
        raise HTTPException(status_code=400, detail="Caracteres inválidos na busca.")

    supabase = get_supabase()
    safe_q = q.strip()

    result = (
        supabase.table("b3_assets")
        .select("ticker, name, type")
        .or_(f"ticker.ilike.%{safe_q}%,name.ilike.%{safe_q}%")
        .not_.like("ticker", "%F")
        .order("ticker")
        .limit(20)
        .execute()
    )

    return {"results": result.data}


@router.get("/")
def list_assets(user_id: str = Depends(get_user_id)):
    """
    Retorna todos os ativos cadastrados na carteira do usuário autenticado,
    enriquecidos com nome e tipo vindos do catálogo da B3.
    """
    supabase = get_supabase()

    # Busca os ativos do usuário
    assets_result = (
        supabase.table("assets")
        .select("id, ticker, created_at")
        .eq("user_id", user_id)
        .order("ticker")
        .execute()
    )

    if not assets_result.data:
        return {"assets": []}

    # Busca os dados do catálogo para os tickers encontrados
    tickers = [a["ticker"] for a in assets_result.data]
    catalog_result = (
        supabase.table("b3_assets")
        .select("ticker, name, type")
        .in_("ticker", tickers)
        .execute()
    )

    # Monta dicionário para lookup rápido por ticker
    catalog_map = {item["ticker"]: item for item in catalog_result.data}

    # Combina os dados
    assets = [
        {
            **asset,
            "name": catalog_map.get(asset["ticker"], {}).get("name"),
            "type": catalog_map.get(asset["ticker"], {}).get("type"),
        }
        for asset in assets_result.data
    ]

    return {"assets": assets}


@router.post("/", status_code=status.HTTP_201_CREATED)
def add_asset(body: AssetCreate, user_id: str = Depends(get_user_id)):
    """
    Adiciona um ativo à carteira do usuário autenticado.
    O ticker é validado pela FK com b3_assets — só aceita ativos reais da B3.
    """
    supabase = get_supabase()

    # Verifica se o ativo já está na carteira
    existing = (
        supabase.table("assets")
        .select("id")
        .eq("user_id", user_id)
        .eq("ticker", body.ticker)
        .execute()
    )

    if existing.data:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ativo já cadastrado na carteira.",
        )

    result = (
        supabase.table("assets")
        .insert({"user_id": user_id, "ticker": body.ticker})
        .execute()
    )

    return {"asset": result.data[0]}


@router.delete("/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_asset(asset_id: str, user_id: str = Depends(get_user_id)):
    """
    Remove um ativo da carteira do usuário autenticado.
    Valida que o ativo pertence ao usuário antes de deletar.
    """
    supabase = get_supabase()

    existing = (
        supabase.table("assets")
        .select("id")
        .eq("id", asset_id)
        .eq("user_id", user_id)
        .execute()
    )

    if not existing.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ativo não encontrado na carteira.",
        )

    supabase.table("assets").delete().eq("id", asset_id).execute()
