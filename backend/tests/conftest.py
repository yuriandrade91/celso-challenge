from collections.abc import Iterator

import pytest

from app.rate_limit import reset_rate_limits
from app.services import providers


@pytest.fixture(autouse=True)
def isolated_process_state(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Limitadores e circuit breakers são por processo: cada teste começa limpo."""
    providers.llm_rate_limiter.cache_clear()
    reset_rate_limits()
    # O .env local pode ligar as métricas emuladas; os testes medem só dados reais.
    monkeypatch.setenv("ENABLE_DEMO_METRICS", "false")
    monkeypatch.setattr(providers, "_OPENAI_CIRCUIT", providers._CircuitBreaker())
    monkeypatch.setattr(providers, "_SMTP_CIRCUIT", providers._CircuitBreaker())
    yield
    reset_rate_limits()


@pytest.fixture(autouse=True)
def fresh_runtime_metrics() -> Iterator[None]:
    from app.metrics import RUNTIME_METRICS

    RUNTIME_METRICS.reset()
    yield
