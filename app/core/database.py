from functools import lru_cache

from supabase import Client, create_client

from app.core.config import settings


@lru_cache(maxsize=1)
def get_supabase() -> Client:
    """
    Retorna uma instância única do cliente Supabase com a service role key.
    Usa cache para evitar múltiplas conexões desnecessárias.
    A service role key bypassa o RLS — usar apenas no servidor, nunca expor ao cliente.
    """
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
