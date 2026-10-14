import asyncio
import json
import logging

import pytest
from fastapi.testclient import TestClient

from app.observability import JsonFormatter
from app.rate_limit import AsyncTokenBucket, SlidingWindowLimiter
from app.services import providers


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_token_bucket_allows_burst_then_paces_requests() -> None:
    clock = FakeClock()
    bucket = AsyncTokenBucket(rate_per_minute=60, burst=2, clock=clock)

    assert bucket.try_acquire() == 0
    assert bucket.try_acquire() == 0
    assert bucket.try_acquire() == pytest.approx(1.0)  # 60/min = 1 por segundo

    clock.now += 1.0
    assert bucket.try_acquire() == 0


def test_token_bucket_acquire_waits_for_capacity(monkeypatch) -> None:
    clock = FakeClock()
    bucket = AsyncTokenBucket(rate_per_minute=120, burst=1, clock=clock)
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock.now += seconds

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    async def two_calls() -> float:
        await bucket.acquire()
        return await bucket.acquire()

    waited = asyncio.run(two_calls())

    assert waited == pytest.approx(0.5)
    assert sleeps == [pytest.approx(0.5)]


def test_llm_calls_are_throttled_by_requests_per_minute(monkeypatch, caplog) -> None:
    from tests.test_resilience import _student

    clock = FakeClock()
    bucket = AsyncTokenBucket(6, clock=clock)  # 6/min: rajada de 1, depois 1 a cada 10 s
    sleeps: list[float] = []

    async def advancing_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock.now += seconds

    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    monkeypatch.setattr(providers, "llm_rate_limiter", lambda _rate: bucket)
    monkeypatch.setattr(asyncio, "sleep", advancing_sleep)
    caplog.set_level(logging.INFO, logger="app.services.providers")
    summarizer = providers.OpenAICompatibleSummarizer()
    content = json.dumps({"bem_em": "a", "atencao_em": "b", "proximos_passos": "c"})
    summarizer._request = lambda _prompt: {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }

    async def two_calls() -> None:
        await summarizer.generate(_student())
        await summarizer.generate(_student())

    asyncio.run(two_calls())

    assert sleeps == [pytest.approx(10.0)]
    assert any(record.getMessage() == "llm.throttled" for record in caplog.records)


def test_sliding_window_limits_per_key_and_reports_retry_after() -> None:
    clock = FakeClock()
    limiter = SlidingWindowLimiter(limit=2, window_seconds=60, clock=clock)

    assert limiter.hit("a") == 0
    clock.now = 10
    assert limiter.hit("a") == 0
    assert limiter.hit("a") == pytest.approx(50)
    assert limiter.hit("b") == 0  # chaves independentes

    clock.now = 60.5
    assert limiter.hit("a") == 0


def test_login_is_rate_limited_with_retry_after(monkeypatch) -> None:
    from app.main import app

    monkeypatch.setenv("LOGIN_RATE_LIMIT_PER_MINUTE", "3")
    client = TestClient(app)

    statuses = [
        client.post("/auth/login", json={"profile": "não-existe"}).status_code
        for _ in range(4)
    ]

    assert statuses[:3] == [422, 422, 422]
    response = client.post("/auth/login", json={"profile": "professor"})
    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) >= 1
    assert response.json()["errors"][0]["code"] == "TOO_MANY_REQUESTS"


def test_rate_limited_event_is_logged(monkeypatch, caplog) -> None:
    from app.main import app

    monkeypatch.setenv("LOGIN_RATE_LIMIT_PER_MINUTE", "1")
    caplog.set_level(logging.WARNING, logger="app.rate_limit")
    client = TestClient(app)
    client.post("/auth/login", json={})
    client.post("/auth/login", json={})

    events = [json.loads(JsonFormatter().format(r)) for r in caplog.records]
    assert any(event.get("event") == "security.rate_limited" for event in events)
