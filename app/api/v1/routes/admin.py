from fastapi import APIRouter, Header, HTTPException, status

from app.core.config import settings
from app.jobs.scheduler import _process_pipeline

router = APIRouter()


def _require_admin_key(x_admin_key: str = Header(..., alias="X-Admin-Key")) -> None:
    """Valida a chave secreta de acesso administrativo."""
    if not settings.ADMIN_SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ADMIN_SECRET_KEY não configurada no servidor.",
        )
    if x_admin_key != settings.ADMIN_SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Chave administrativa inválida.",
        )


@router.post("/run-pipeline", status_code=status.HTTP_200_OK)
async def run_pipeline_manually(
    days_back: int = 7,
    _: None = None,
    x_admin_key: str = Header(..., alias="X-Admin-Key"),
):
    """
    Dispara o pipeline manualmente.
    Requer header X-Admin-Key com o valor de ADMIN_SECRET_KEY.
    """
    _require_admin_key(x_admin_key)
    await _process_pipeline(days_back=days_back)
    return {"message": f"Pipeline executado para os últimos {days_back} dia(s)."}
