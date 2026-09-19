import re

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status

from app.core.database import get_supabase
from datetime import timedelta

from app.core.rate_limit import excedeu
from app.core.security import get_user_id
from postgrest.exceptions import APIError

from app.jobs.scheduler import backfill_asset_sync, register_backfill, reservar_backfill
from app.models.schemas import AssetCreate

router = APIRouter()

_SEARCH_ALLOWED = re.compile(r"^[A-Za-z0-9 ]+$")

# O produto é gratuito, então o que segura o custo é o número de tickers
# distintos: cada ticker inédito dispara um backfill de 60 dias com chamadas
# de IA. Carteiras reais ficam entre 5 e 20 ativos; 30 dá folga para elas e
# impede que uma conta sozinha transforme cadastro em centenas de backfills.
MAX_ASSETS_PER_USER = 30


@router.get("/search")
def search_b3_assets(request: Request, q: str = Query(min_length=1, max_length=20)):
    """
    Busca ativos no catálogo da B3 pelo ticker ou nome.
    Endpoint público para autocomplete, não exige autenticação.
    """
    forwarded = request.headers.get("X-Forwarded-For")
    ip = forwarded.split(",")[-1].strip() if forwarded else (request.client.host if request.client else "unknown")
    # Autocomplete com debounce: quem procura três ou quatro ativos seguidos
    # passa de 5 por minuto sem estar abusando de nada.
    if excedeu(f"busca:{ip}", 40, timedelta(minutes=1)):
        raise HTTPException(status_code=429, detail="Muitas buscas seguidas. Aguarde um instante.")

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
def add_asset(
    body: AssetCreate,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_user_id),
):
    """
    Adiciona um ativo à carteira do usuário autenticado.
    O ticker é validado pela FK com b3_assets, só aceita ativos reais da B3.

    Se o ticker ainda não tem nenhum relatório no banco, dispara em segundo
    plano o backfill dos últimos 2 meses, para o dashboard não nascer vazio.
    Quando já há relatórios, o job diário vem acumulando e não há o que buscar.

    Devolve backfill_queued para a interface saber se deve avisar o usuário
    de que os relatórios vão levar alguns minutos para aparecer.
    """
    # Cadastrar ativos em sequência no primeiro uso é normal; o que este teto
    # corta é o ciclo de adicionar e remover sem parar.
    if excedeu(f"ativo:{user_id}", 40, timedelta(hours=1)):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Muitas alterações seguidas na carteira. Tente de novo em alguns minutos.",
        )

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

    total = (
        supabase.table("assets")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .execute()
        .count
        or 0
    )
    if total >= MAX_ASSETS_PER_USER:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Limite de {MAX_ASSETS_PER_USER} ativos por conta atingido.",
        )

    # O trigger do banco é quem garante o limite (a contagem acima pode
    # perder uma corrida entre duas requisições simultâneas). Quando ele
    # barra, a resposta tem de ser a mesma mensagem legível, não um 500.
    try:
        result = (
            supabase.table("assets")
            .insert({"user_id": user_id, "ticker": body.ticker})
            .execute()
        )
    except APIError as e:
        if "Limite" in str(e):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Limite de {MAX_ASSETS_PER_USER} ativos por conta atingido.",
            )
        raise

    # Backfill só para ticker sem histórico. backfill_asset() repete essa
    # verificação por dentro, o que também cobre duas pessoas adicionando o
    # mesmo ativo ao mesmo tempo.
    has_reports = bool(
        supabase.table("reports")
        .select("id")
        .eq("ticker", body.ticker)
        .limit(1)
        .execute()
        .data
    )

    agendar = not has_reports and reservar_backfill(body.ticker)

    if agendar:
        # Registrar antes de agendar: quem cadastra vários ativos seguidos cai
        # no mesmo lote e recebe um aviso só, quando o último terminar.
        register_backfill(user_id, body.ticker)
        background_tasks.add_task(backfill_asset_sync, body.ticker, user_id)

    return {"asset": result.data[0], "backfill_queued": agendar}


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
