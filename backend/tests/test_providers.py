import asyncio
import json
import logging
from email.message import EmailMessage

import pytest

from app.observability import JsonFormatter
from app.schemas.reports import AlunoCSV
from app.services import providers
from app.services.providers import (
    MockGradeReportNotifier,
    MockSummarizer,
    OpenAICompatibleSummarizer,
    SMTPGradeReportNotifier,
)


VALID_JSON = json.dumps(
    {
        "bem_em": "Matemática, com ótima nota.",
        "atencao_em": "História, abaixo da média.",
        "proximos_passos": "Revise os capítulos 3 e 4 de História.",
    }
)


def _student() -> AlunoCSV:
    return AlunoCSV.model_validate(
        {
            "id_aluno": "7f3c2a10-4b8e-4e21-9d55-0c6a1b2e9f01",
            "nome": "Maria Souza",
            "email": "maria@example.com",
            "nota_matematica": "17.5",
            "nota_historia": "8",
        }
    )


def test_mock_summarizer_personalizes_feedback_and_estimates_cost(
    monkeypatch,
) -> None:
    monkeypatch.setenv("LLM_INPUT_USD_PER_1K_TOKENS", "0.001")
    monkeypatch.setenv("LLM_OUTPUT_USD_PER_1K_TOKENS", "0.002")
    result = asyncio.run(MockSummarizer().generate(_student()))

    assert "Olá Maria Souza" in result.summary
    assert "foi bem em Matemática" in result.summary
    assert "Atenção em História" in result.summary
    assert result.prompt_tokens > 0
    assert result.completion_tokens > 0
    assert result.estimated_cost_usd == pytest.approx(
        (result.prompt_tokens * 0.001 + result.completion_tokens * 0.002) / 1000
    )
    assert result.used_fallback is False


@pytest.mark.parametrize(
    ("math_grade", "history_grade", "expected"),
    [
        ("15", "16", "foi bem em Matemática e História"),
        ("4", "6", "Atenção em Matemática e História"),
    ],
)
def test_template_summary_reads_naturally_for_all_grade_profiles(
    math_grade: str, history_grade: str, expected: str
) -> None:
    student = _student().model_copy(
        update={
            "nota_matematica": float(math_grade),
            "nota_historia": float(history_grade),
        }
    )

    assert expected in providers.template_summary(student)


def test_count_tokens_falls_back_when_tokenizer_is_unavailable(
    monkeypatch,
) -> None:
    monkeypatch.setattr(providers, "_token_encoding", lambda: None)

    assert providers.count_tokens("abcdefg") == 3


class _FailingSummarizer(providers.ISummarizer):
    def __init__(self, error: Exception) -> None:
        self.error = error

    @property
    def provider_name(self) -> str:
        return "failing"

    async def generate(self, student: AlunoCSV) -> providers.SummaryResult:
        raise self.error


@pytest.mark.parametrize(
    "error",
    [
        providers.ProviderCircuitOpenError("circuit open"),
        providers.TransientProviderError("timeout"),
        providers.ProviderRequestError("HTTP 400"),
    ],
)
def test_fallback_summarizer_degrades_to_template_on_provider_errors(
    error: Exception,
) -> None:
    summarizer = providers.FallbackSummarizer(
        _FailingSummarizer(error), providers.TemplateSummarizer()
    )

    result = asyncio.run(summarizer.generate(_student()))

    assert result.used_fallback is True
    assert result.summary == providers.template_summary(_student())
    assert result.prompt_tokens == result.completion_tokens == 0
    assert result.estimated_cost_usd == 0


def test_fallback_summarizer_does_not_hide_programming_errors() -> None:
    summarizer = providers.FallbackSummarizer(
        _FailingSummarizer(KeyError("bug")), providers.TemplateSummarizer()
    )

    with pytest.raises(KeyError):
        asyncio.run(summarizer.generate(_student()))


def test_openai_provider_is_wrapped_with_template_fallback_by_default(
    monkeypatch,
) -> None:
    monkeypatch.setenv("GRADE_SUMMARY_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    monkeypatch.delenv("GRADE_SUMMARY_FALLBACK", raising=False)
    assert isinstance(
        providers.create_summarizer(), providers.FallbackSummarizer
    )

    monkeypatch.setenv("GRADE_SUMMARY_FALLBACK", "none")
    assert isinstance(
        providers.create_summarizer(), OpenAICompatibleSummarizer
    )


def test_openai_compatible_summarizer_uses_provider_usage_and_price(
    monkeypatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    monkeypatch.setenv("LLM_INPUT_USD_PER_1K_TOKENS", "0.001")
    monkeypatch.setenv("LLM_OUTPUT_USD_PER_1K_TOKENS", "0.002")
    summarizer = OpenAICompatibleSummarizer()
    summarizer._request = lambda _prompt: {
        "choices": [{"message": {"content": VALID_JSON}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20},
    }

    result = asyncio.run(summarizer.generate(_student()))

    assert result.summary.startswith("Olá Maria Souza!")
    assert "Você foi bem em: Matemática, com ótima nota." in result.summary
    assert "Próximos passos: Revise os capítulos 3 e 4 de História." in result.summary
    assert result.prompt_tokens == 100
    assert result.completion_tokens == 20
    assert result.estimated_cost_usd == pytest.approx(0.00014)


def test_openai_request_sends_auth_and_token_cap_without_network(
    monkeypatch,
) -> None:
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return b'{"choices":[],"usage":{"prompt_tokens":1,"completion_tokens":1}}'

    def fake_urlopen(request, timeout):
        captured["authorization"] = request.get_header("Authorization")
        captured["payload"] = json.loads(request.data)
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    monkeypatch.setenv("LLM_MAX_COMPLETION_TOKENS", "64")
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    summarizer = OpenAICompatibleSummarizer()

    summarizer._request("test prompt")

    assert captured["authorization"] == "Bearer test-only"
    assert captured["payload"]["max_tokens"] == 64
    assert captured["timeout"] == 30


def test_openai_summarizer_retries_transient_provider_failures(
    monkeypatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    monkeypatch.setattr(providers, "_jitter_wait", lambda _retry_state: 0)
    summarizer = OpenAICompatibleSummarizer()
    attempts = 0

    def transient_then_success(_prompt):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise providers.TransientProviderError("temporary failure")
        return {
            "choices": [{"message": {"content": VALID_JSON}}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 3},
        }

    summarizer._request = transient_then_success

    result = asyncio.run(summarizer.generate(_student()))

    assert "Atenção em: História, abaixo da média." in result.summary
    assert attempts == 3


def test_smtp_notifier_builds_message_for_student_without_network(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            captured["connection"] = (host, port, timeout)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def ehlo(self):
            pass

        def starttls(self, context):
            captured["tls"] = context

        def login(self, username, password):
            captured["credentials"] = (username, password)

        def send_message(self, message: EmailMessage):
            captured["message"] = message

    monkeypatch.setenv("SMTP_HOST", "mail.example.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_FROM", "reports@example.com")
    monkeypatch.setenv("SMTP_USERNAME", "mailer")
    monkeypatch.setenv("SMTP_PASSWORD", "secret-for-test")
    monkeypatch.setenv("SMTP_USE_SSL", "false")
    monkeypatch.setattr("smtplib.SMTP", FakeSMTP)
    notifier = SMTPGradeReportNotifier()

    notifier._send("maria@example.com", "Seu resumo")

    message = captured["message"]
    assert message["To"] == "maria@example.com"
    assert message["From"] == "reports@example.com"
    assert message.get_content().strip() == "Seu resumo"
    assert captured["credentials"] == ("mailer", "secret-for-test")


def test_mock_notifier_logs_masked_recipient_and_never_message(caplog) -> None:
    caplog.set_level(logging.INFO, logger="app.services.providers")
    asyncio.run(
        MockGradeReportNotifier().send_notification(
            "maria@example.com", "Sensitive grade summary"
        )
    )

    emitted = "\n".join(JsonFormatter().format(record) for record in caplog.records)
    event = json.loads(emitted)

    assert event["event"] == "grade_report.notification.sent"
    assert event["recipient"] == "m***@example.com"
    assert "Sensitive grade summary" not in emitted
    assert "maria@example.com" not in emitted


def test_circuit_breaker_blocks_and_allows_single_half_open_probe(
    monkeypatch,
) -> None:
    clock = [100.0]
    monkeypatch.setattr(providers.time, "monotonic", lambda: clock[0])
    breaker = providers._CircuitBreaker(
        failure_threshold=2, reset_after_seconds=30
    )

    breaker.record_failure()
    breaker.record_failure()
    try:
        breaker.before_call()
    except providers.ProviderCircuitOpenError:
        pass
    else:
        raise AssertionError("Circuit should reject calls while open.")

    clock[0] = 131.0
    breaker.before_call()
    try:
        breaker.before_call()
    except providers.ProviderCircuitOpenError:
        pass
    else:
        raise AssertionError("Only one half-open probe should be allowed.")
    breaker.record_success()
    breaker.before_call()


def test_retry_after_header_parsing() -> None:
    assert providers._parse_retry_after(None) is None
    assert providers._parse_retry_after("7") == 7
    assert providers._parse_retry_after("not-a-date") is None
    assert providers._parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT") == 0


def test_jittered_backoff_stays_within_bounds() -> None:
    from tenacity import RetryCallState

    state = RetryCallState(None, None, (), {})
    state.attempt_number = 3
    waits = {providers._jitter_wait(state) for _ in range(50)}

    assert all(0 <= wait <= 8 for wait in waits)
    assert len(waits) > 1


def _llm_with_errors(monkeypatch, errors):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    monkeypatch.setattr(providers, "_OPENAI_CIRCUIT", providers._CircuitBreaker())
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(providers.asyncio, "sleep", fake_sleep)
    summarizer = OpenAICompatibleSummarizer()
    calls = 0

    def request(_prompt):
        nonlocal calls
        calls += 1
        if errors:
            raise errors.pop(0)
        return {
            "choices": [{"message": {"content": VALID_JSON}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }

    summarizer._request = request
    return summarizer, sleeps, lambda: calls


def test_retry_honours_retry_after_from_provider(monkeypatch) -> None:
    summarizer, sleeps, calls = _llm_with_errors(
        monkeypatch,
        [providers.TransientProviderError("HTTP 429", retry_after=2.5)],
    )

    asyncio.run(summarizer.generate(_student()))

    assert calls() == 2
    assert sleeps == [2.5]


def test_long_retry_after_fails_fast(monkeypatch) -> None:
    summarizer, sleeps, calls = _llm_with_errors(
        monkeypatch,
        [providers.TransientProviderError("HTTP 429", retry_after=120)],
    )

    with pytest.raises(providers.TransientProviderError):
        asyncio.run(summarizer.generate(_student()))

    assert calls() == 1
    assert sleeps == []


def test_fatal_provider_errors_are_not_retried(monkeypatch) -> None:
    summarizer, sleeps, calls = _llm_with_errors(
        monkeypatch, [providers.ProviderRequestError("HTTP 400")]
    )

    with pytest.raises(providers.ProviderRequestError):
        asyncio.run(summarizer.generate(_student()))

    assert calls() == 1
    assert sleeps == []


def test_openai_http_429_carries_retry_after(monkeypatch) -> None:
    import io
    import urllib.error
    from email.message import Message

    headers = Message()
    headers["Retry-After"] = "3"

    def fake_urlopen(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url, 429, "Too Many Requests", headers, io.BytesIO()
        )

    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(providers.TransientProviderError) as raised:
        OpenAICompatibleSummarizer()._request("prompt")

    assert raised.value.retry_after == 3


def test_smtp_transient_failure_is_retried_then_delivered(monkeypatch) -> None:
    import smtplib

    monkeypatch.setattr(providers, "_SMTP_CIRCUIT", providers._CircuitBreaker())
    monkeypatch.setattr(providers, "_jitter_wait", lambda _retry_state: 0)
    monkeypatch.setenv("SMTP_HOST", "mail.example.com")
    monkeypatch.setenv("SMTP_FROM", "reports@example.com")
    notifier = SMTPGradeReportNotifier()
    attempts = 0

    def flaky_send(_recipient, _message):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise smtplib.SMTPResponseException(421, b"try later")

    notifier._send = flaky_send

    asyncio.run(notifier.send_notification("maria@example.com", "Resumo"))

    assert attempts == 2


def test_smtp_permanent_rejection_is_not_retried(monkeypatch) -> None:
    import smtplib

    monkeypatch.setattr(providers, "_SMTP_CIRCUIT", providers._CircuitBreaker())
    monkeypatch.setenv("SMTP_HOST", "mail.example.com")
    monkeypatch.setenv("SMTP_FROM", "reports@example.com")
    notifier = SMTPGradeReportNotifier()
    attempts = 0

    def rejected(_recipient, _message):
        nonlocal attempts
        attempts += 1
        raise smtplib.SMTPResponseException(550, b"no such user")

    notifier._send = rejected

    with pytest.raises(providers.ProviderRequestError):
        asyncio.run(notifier.send_notification("maria@example.com", "Resumo"))

    assert attempts == 1
