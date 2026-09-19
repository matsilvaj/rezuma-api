"""
Limites de frequência em memória.

Cada uso tem o próprio balde, identificado por um prefixo na chave: a busca
pública não pode gastar a cota do endpoint administrativo, e vice-versa.

Vale por processo. Com uma instância só no Railway isso é suficiente; se um
dia houver várias réplicas, cada uma conta separado e o limite efetivo se
multiplica pelo número delas, e aí o lugar certo passa a ser um Redis.
"""

import logging
import threading
from collections import defaultdict
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# Acima disso, a próxima chamada varre chaves sem uso recente. Sem poda, cada
# IP que já passou pela busca pública ficava na memória para sempre.
_PODAR_ACIMA_DE = 5_000
_JANELA_MAXIMA = timedelta(hours=1)

_lock = threading.Lock()
_eventos: dict[str, list[datetime]] = defaultdict(list)

# Bloqueio por tentativas erradas na chave de administração.
_BLOCK_AFTER_FAILURES = 5
_FAILURE_WINDOW = timedelta(minutes=10)
_BLOCK_DURATION = timedelta(hours=1)
_failures: dict[str, list[datetime]] = defaultdict(list)
_blocked_until: dict[str, datetime] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _podar(agora: datetime) -> None:
    for chave in [k for k, v in _eventos.items() if not v or agora - v[-1] > _JANELA_MAXIMA]:
        del _eventos[chave]
    for ip in [k for k, v in _failures.items() if not v or agora - v[-1] > _FAILURE_WINDOW]:
        del _failures[ip]
    for ip in [k for k, ate in _blocked_until.items() if agora >= ate]:
        del _blocked_until[ip]


def excedeu(chave: str, limite: int, janela: timedelta) -> bool:
    """
    Registra uma ocorrência para a chave e diz se ela passou do limite na janela.

    A ocorrência conta mesmo quando excede: quem insiste continua bloqueado
    até parar de insistir, em vez de ganhar uma vaga a cada requisição negada.
    """
    agora = _now()
    with _lock:
        if len(_eventos) > _PODAR_ACIMA_DE:
            _podar(agora)
        recentes = [t for t in _eventos[chave] if agora - t < janela]
        recentes.append(agora)
        _eventos[chave] = recentes
        return len(recentes) > limite


def is_rate_limited(ip: str) -> bool:
    """Endpoint administrativo: 5 chamadas por minuto por IP."""
    return excedeu(f"admin:{ip}", 5, timedelta(minutes=1))


def is_ip_blocked(ip: str) -> bool:
    with _lock:
        until = _blocked_until.get(ip)
        if not until:
            return False
        if _now() < until:
            return True
        del _blocked_until[ip]
        _failures.pop(ip, None)
        return False


def record_failure(ip: str) -> None:
    now = _now()
    with _lock:
        _failures[ip] = [t for t in _failures[ip] if now - t < _FAILURE_WINDOW]
        _failures[ip].append(now)
        if len(_failures[ip]) >= _BLOCK_AFTER_FAILURES:
            _blocked_until[ip] = now + _BLOCK_DURATION
            logger.warning(f"Admin: IP {ip} bloqueado por 1h após {_BLOCK_AFTER_FAILURES} tentativas falhas.")


def record_success(ip: str) -> None:
    with _lock:
        _failures.pop(ip, None)
