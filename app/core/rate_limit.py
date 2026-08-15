import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

_RATE_LIMIT = 5
_RATE_WINDOW = timedelta(minutes=1)

_BLOCK_AFTER_FAILURES = 5
_FAILURE_WINDOW = timedelta(minutes=10)
_BLOCK_DURATION = timedelta(hours=1)

_request_times: dict[str, list[datetime]] = defaultdict(list)
_failures: dict[str, list[datetime]] = defaultdict(list)
_blocked_until: dict[str, datetime] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def is_rate_limited(ip: str) -> bool:
    now = _now()
    _request_times[ip] = [t for t in _request_times[ip] if now - t < _RATE_WINDOW]
    _request_times[ip].append(now)
    return len(_request_times[ip]) > _RATE_LIMIT


def is_ip_blocked(ip: str) -> bool:
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
    _failures[ip] = [t for t in _failures[ip] if now - t < _FAILURE_WINDOW]
    _failures[ip].append(now)
    if len(_failures[ip]) >= _BLOCK_AFTER_FAILURES:
        _blocked_until[ip] = now + _BLOCK_DURATION
        logger.warning(f"Admin: IP {ip} bloqueado por 1h após {_BLOCK_AFTER_FAILURES} tentativas falhas.")


def record_success(ip: str) -> None:
    _failures.pop(ip, None)
