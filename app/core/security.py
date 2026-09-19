import hashlib
import time

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings

bearer_scheme = HTTPBearer()

# Validar o token custa uma ida ao Supabase, e abrir o painel dispara várias
# requisições em paralelo com o mesmo token (uma por página de relatórios,
# mais a de ativos). Guardar a resposta por pouco tempo corta essas idas.
#
# O preço é que um logout demora até _TOKEN_TTL segundos para valer aqui.
# Um minuto é o equilíbrio: o token do Supabase já vive uma hora por padrão.
# A chave é o hash do token, para o token em si não ficar na memória.
_TOKEN_TTL = 60
_TOKEN_CACHE_MAX = 2_000
_token_cache: dict[str, tuple[float, dict]] = {}


def _chave(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> dict:
    """
    Valida o JWT chamando diretamente o endpoint de usuário do Supabase Auth.
    Funciona com qualquer algoritmo (HS256, ES256) sem depender do cliente Supabase.
    """
    token = credentials.credentials
    chave = _chave(token)
    agora = time.monotonic()

    em_cache = _token_cache.get(chave)
    if em_cache and agora - em_cache[0] < _TOKEN_TTL:
        return em_cache[1]

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(
            f"{settings.SUPABASE_URL}/auth/v1/user",
            headers={
                "Authorization": f"Bearer {token}",
                "apikey": settings.SUPABASE_ANON_KEY,
            },
        )

    if response.status_code != 200:
        # Recusa nunca vai para o cache: um token que falhou por instabilidade
        # do Supabase precisa poder passar na próxima tentativa.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido.",
        )

    usuario = response.json()

    if len(_token_cache) >= _TOKEN_CACHE_MAX:
        for k in [k for k, (quando, _) in _token_cache.items() if agora - quando >= _TOKEN_TTL]:
            del _token_cache[k]
        # Ainda cheio só com entradas válidas: esvazia, o custo é revalidar.
        if len(_token_cache) >= _TOKEN_CACHE_MAX:
            _token_cache.clear()

    _token_cache[chave] = (agora, usuario)
    return usuario


def get_user_id(current_user: dict = Depends(get_current_user)) -> str:
    """Extrai e retorna o ID do usuário autenticado a partir do payload do Supabase."""
    user_id = current_user.get("id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuário não identificado.",
        )
    return user_id
