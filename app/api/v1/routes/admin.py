import hmac

from fastapi import APIRouter, Header, HTTPException, Query, Request, status

from app.core.config import settings
from app.core.rate_limit import is_ip_blocked, is_rate_limited, record_failure, record_success
from app.jobs.scheduler import _process_pipeline

router = APIRouter()


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        # Último IP da cadeia — adicionado pelo proxy do Railway, não pode ser falsificado pelo cliente
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def _require_admin(request: Request, x_admin_key: str) -> None:
    ip = _client_ip(request)

    if is_rate_limited(ip) or is_ip_blocked(ip):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many requests.")

    if not settings.ADMIN_SECRET_KEY:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="ADMIN_SECRET_KEY não configurada.")

    if not hmac.compare_digest(x_admin_key, settings.ADMIN_SECRET_KEY):
        record_failure(ip)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Chave administrativa inválida.")

    record_success(ip)


@router.post("/run-pipeline", status_code=status.HTTP_200_OK)
async def run_pipeline_manually(
    request: Request,
    days_back: int = Query(default=7, ge=1, le=90),
    x_admin_key: str = Header(..., alias="X-Admin-Key"),
):
    """Dispara o pipeline manualmente. Requer header X-Admin-Key."""
    _require_admin(request, x_admin_key)
    await _process_pipeline(days_back=days_back)
    return {"message": f"Pipeline executado para os últimos {days_back} dia(s)."}
