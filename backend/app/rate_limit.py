import asyncio
import logging
import math
import os
import threading
import time
from collections import deque
from collections.abc import Callable

from fastapi import Depends, HTTPException, Request, status

from app.auth.dependencies import require_teacher
from app.domain.exceptions import ConfigurationError
from app.observability import log_event
from app.schemas.auth import AuthenticatedUser

logger = logging.getLogger(__name__)


class AsyncTokenBucket:
    """Throttling de saída: no máximo `rate_per_minute` chamadas, com rajada limitada.

    O estado é protegido por um lock de thread (a secção crítica não faz await),
    o que o torna seguro entre loops de eventos e threads do mesmo processo.
    """

    def __init__(
        self,
        rate_per_minute: float,
        burst: int | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if rate_per_minute <= 0:
            raise ConfigurationError("O limite por minuto deve ser positivo.")
        self.rate_per_second = rate_per_minute / 60
        self.capacity = float(burst or max(1, math.ceil(rate_per_minute / 10)))
        self._tokens = self.capacity
        self._clock = clock
        self._updated_at = clock()
        self._lock = threading.Lock()

    def try_acquire(self) -> float:
        """Consome um token e devolve 0, ou devolve quantos segundos esperar."""
        with self._lock:
            now = self._clock()
            self._tokens = min(
                self.capacity,
                self._tokens + (now - self._updated_at) * self.rate_per_second,
            )
            self._updated_at = now
            if self._tokens >= 1:
                self._tokens -= 1
                return 0.0
            return (1 - self._tokens) / self.rate_per_second

    async def acquire(self) -> float:
        """Espera até haver capacidade; devolve o tempo total de espera."""
        waited = 0.0
        while (wait := self.try_acquire()) > 0:
            await asyncio.sleep(wait)
            waited += wait
        return waited


class SlidingWindowLimiter:
    """Limite de entrada por chave (IP ou utilizador) numa janela deslizante."""

    def __init__(
        self, limit: int, window_seconds: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str) -> float:
        """Regista um pedido; devolve 0 se permitido ou o Retry-After em segundos."""
        with self._lock:
            now = self._clock()
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= now - self.window_seconds:
                hits.popleft()
            if len(hits) >= self.limit:
                return max(hits[0] + self.window_seconds - now, 0.001)
            hits.append(now)
            return 0.0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


_LIMITERS: dict[tuple[str, int], SlidingWindowLimiter] = {}
_LIMITERS_LOCK = threading.Lock()


def _per_minute(env_name: str, default: int) -> int:
    try:
        value = int(os.getenv(env_name, str(default)))
    except ValueError as error:
        raise ConfigurationError(f"{env_name} deve ser um inteiro.") from error
    if value < 1:
        raise ConfigurationError(f"{env_name} deve ser positivo.")
    return value


def _limiter(name: str, limit: int) -> SlidingWindowLimiter:
    with _LIMITERS_LOCK:
        return _LIMITERS.setdefault((name, limit), SlidingWindowLimiter(limit, 60))


def reset_rate_limits() -> None:
    with _LIMITERS_LOCK:
        for limiter in _LIMITERS.values():
            limiter.reset()


def _enforce(name: str, key: str, limit: int) -> None:
    retry_after = _limiter(name, limit).hit(key)
    if retry_after:
        log_event(
            logger,
            "security.rate_limited",
            logging.WARNING,
            limiter=name,
            limit_per_minute=limit,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiados pedidos. Tente novamente em instantes.",
            headers={"Retry-After": str(math.ceil(retry_after))},
        )


def limit_login(request: Request) -> None:
    """Protege login e refresh contra força bruta, por IP de origem.

    Atrás do painel Next.js todos os pedidos chegam do mesmo servidor; em
    produção a chave viria de X-Forwarded-For definido por um proxy confiável.
    """
    client = request.client.host if request.client else "unknown"
    _enforce("auth", client, _per_minute("LOGIN_RATE_LIMIT_PER_MINUTE", 10))


def limit_upload(
    current_user: AuthenticatedUser = Depends(require_teacher),
) -> AuthenticatedUser:
    """Evita disparos repetidos de uploads (custo de LLM), por professor."""
    _enforce(
        "upload",
        current_user.email,
        _per_minute("UPLOAD_RATE_LIMIT_PER_MINUTE", 10),
    )
    return current_user


def limit_term_close(
    current_user: AuthenticatedUser = Depends(require_teacher),
) -> AuthenticatedUser:
    """Cada fecho de semestre chama o LLM para toda a turma: limite por professor."""
    _enforce(
        "term_close",
        current_user.email,
        _per_minute("TERM_CLOSE_RATE_LIMIT_PER_MINUTE", 5),
    )
    return current_user
