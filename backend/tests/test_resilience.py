"""Idempotência entre execuções concorrentes, orçamento de custo e contrato do LLM."""

import asyncio
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.interfaces.interfaces import INotifier, ISummarizer, SummaryResult
from app.repositories.reports import ReportRepository
from app.schemas.reports import AlunoCSV
from app.services import providers
from app.services.reports import ExecutionBudget, process_csv

HEADER = "id_aluno,nome,email,nota_matematica,nota_historia\n"


def _rows(count: int) -> bytes:
    return (
        HEADER
        + "".join(
            f"7f3c2a10-4b8e-4e21-9d55-0c6a1b2e9f{i:02d},Aluno {i},"
            f"aluno{i}@example.com,{8 + i % 10},12\n"
            for i in range(1, count + 1)
        )
    ).encode()


class SlowNotifier(INotifier):
    def __init__(self) -> None:
        self.deliveries: list[str] = []

    async def send_notification(self, recipient: str, message: str) -> None:
        await asyncio.sleep(0.02)
        self.deliveries.append(recipient)


class CountingSummarizer(ISummarizer):
    def __init__(self, cost: float = 0.001) -> None:
        self.calls = 0
        self.cost = cost

    @property
    def provider_name(self) -> str:
        return "counting"

    def estimate_max_cost(self, student: AlunoCSV) -> float:
        return self.cost

    async def generate(self, student: AlunoCSV) -> SummaryResult:
        self.calls += 1
        await asyncio.sleep(0.01)
        return SummaryResult(f"Resumo de {student.nome}", 10, 5, self.cost)


@pytest.fixture
def file_engine(tmp_path: Path):
    # Ficheiro real: cada execução tem a sua ligação, como dois pedidos HTTP.
    engine = create_engine(
        f"sqlite:///{tmp_path / 'dispatch.db'}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


def test_concurrent_uploads_of_the_same_file_notify_each_student_once(
    file_engine,
) -> None:
    content = _rows(6)
    notifier = SlowNotifier()
    summarizer = CountingSummarizer()

    async def both() -> list:
        with Session(file_engine) as first_db, Session(file_engine) as second_db:
            return await asyncio.gather(
                process_csv(content, ReportRepository(first_db), notifier, summarizer),
                process_csv(content, ReportRepository(second_db), notifier, summarizer),
            )

    first, second = asyncio.run(both())

    assert len(notifier.deliveries) == 6
    assert sorted(notifier.deliveries) == sorted(set(notifier.deliveries))
    assert summarizer.calls == 6
    assert first.processados + second.processados == 6
    assert (
        first.em_processamento
        + second.em_processamento
        + first.ignorados_cache
        + second.ignorados_cache
        == 6
    )


def test_claim_is_exclusive_until_released_or_expired(file_engine, monkeypatch) -> None:
    clock = [1_000.0]
    monkeypatch.setattr("app.repositories.reports.time.time", lambda: clock[0])
    student_id = "7f3c2a10-4b8e-4e21-9d55-0c6a1b2e9f01"

    with Session(file_engine) as db:
        repository = ReportRepository(db)
        assert repository.claim_report(student_id, "exec-a", 60) is True
        assert repository.claim_report(student_id, "exec-a", 60) is True
        assert repository.claim_report(student_id, "exec-b", 60) is False

        clock[0] += 61  # lease expirado: uma execução que caiu não bloqueia
        assert repository.claim_report(student_id, "exec-b", 60) is True

        repository.release_report(student_id, "exec-a")  # não é o dono
        assert repository.claim_report(student_id, "exec-c", 60) is False
        repository.release_report(student_id, "exec-b")
        assert repository.claim_report(student_id, "exec-c", 60) is True


def test_execution_budget_reserves_before_spending() -> None:
    budget = ExecutionBudget(max_cost_usd=0.003)

    assert budget.reserve(0.001)
    assert budget.reserve(0.001)
    assert budget.reserve(0.001)
    assert not budget.reserve(0.001)  # reservas pendentes também contam
    budget.settle(0.001, 0.0002)
    assert budget.reserve(0.0005)
    assert budget.exhausted


def test_budget_cap_switches_remaining_students_to_template(
    monkeypatch, file_engine
) -> None:
    monkeypatch.setenv("GRADE_MAX_COST_USD_PER_EXECUTION", "0.0025")
    monkeypatch.setenv("GRADE_MAX_CONCURRENCY", "1")
    summarizer = CountingSummarizer(cost=0.001)
    notifier = SlowNotifier()

    with Session(file_engine) as db:
        report = asyncio.run(
            process_csv(_rows(5), ReportRepository(db), notifier, summarizer)
        )

    assert summarizer.calls == 2
    assert report.processados == 5
    assert report.fallbacks_llm == 3
    assert report.orcamento_excedido is True
    assert report.custo_estimado_usd == pytest.approx(0.002)
    assert len(notifier.deliveries) == 5


def test_invalid_budget_configuration_is_rejected(monkeypatch) -> None:
    from app.domain.exceptions import ConfigurationError
    from tests.test_business import FakeNotifier, MemoryReportRepository

    monkeypatch.setenv("GRADE_MAX_COST_USD_PER_EXECUTION", "-1")

    with pytest.raises(ConfigurationError):
        asyncio.run(
            process_csv(
                _rows(1), MemoryReportRepository(), FakeNotifier(), CountingSummarizer()
            )
        )


def _student(name: str = "Maria Souza") -> AlunoCSV:
    return AlunoCSV.model_validate(
        {
            "id_aluno": "7f3c2a10-4b8e-4e21-9d55-0c6a1b2e9f01",
            "nome": name,
            "email": "maria@example.com",
            "nota_matematica": "17.5",
            "nota_historia": "8",
        }
    )


def test_prompt_fits_token_budget_by_truncating_only_the_name(monkeypatch) -> None:
    long_name = "Maria " + "Silva " * 19
    untouched = providers.build_prompt(_student(long_name))
    full_tokens = providers.count_tokens(untouched) + providers.count_tokens(
        providers._SYSTEM_PROMPT
    )
    monkeypatch.setenv("LLM_MAX_PROMPT_TOKENS", str(full_tokens - 10))

    prompt = providers.build_prompt(_student(long_name))

    assert providers.count_tokens(prompt) + providers.count_tokens(
        providers._SYSTEM_PROMPT
    ) <= full_tokens - 10
    assert "Matemática: 17.5/20" in prompt
    assert "História: 8/20" in prompt
    assert "Responda SOMENTE com um objeto JSON" in prompt
    assert long_name not in prompt


def test_prompt_budget_too_small_for_instructions_is_a_configuration_error(
    monkeypatch,
) -> None:
    monkeypatch.setenv("LLM_MAX_PROMPT_TOKENS", "50")

    with pytest.raises(providers.ProviderConfigurationError):
        providers.build_prompt(_student())


@pytest.mark.parametrize(
    "content",
    [
        "Texto livre sem JSON",
        json.dumps({"bem_em": "Matemática"}),
        json.dumps({"bem_em": "", "atencao_em": "x", "proximos_passos": "y"}),
        json.dumps(
            {"bem_em": "x" * 301, "atencao_em": "x", "proximos_passos": "y"}
        ),
    ],
)
def test_llm_output_outside_contract_falls_back_and_keeps_cost(
    monkeypatch, content: str
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    monkeypatch.setenv("LLM_INPUT_USD_PER_1K_TOKENS", "1")
    monkeypatch.setenv("LLM_OUTPUT_USD_PER_1K_TOKENS", "1")
    primary = providers.OpenAICompatibleSummarizer()
    primary._request = lambda _prompt: {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50},
    }
    summarizer = providers.FallbackSummarizer(primary, providers.TemplateSummarizer())

    result = asyncio.run(summarizer.generate(_student()))

    assert result.used_fallback is True
    assert result.summary == providers.template_summary(_student())
    assert result.prompt_tokens == 100
    assert result.completion_tokens == 50
    assert result.estimated_cost_usd == pytest.approx(0.15)


def test_openai_request_asks_for_json_object(monkeypatch) -> None:
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return b"{}"

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data)
        return FakeResponse()

    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    providers.OpenAICompatibleSummarizer()._request("prompt")

    assert captured["payload"]["response_format"] == {"type": "json_object"}


def test_estimated_max_cost_covers_actual_cost(monkeypatch) -> None:
    monkeypatch.setenv("LLM_INPUT_USD_PER_1K_TOKENS", "0.001")
    monkeypatch.setenv("LLM_OUTPUT_USD_PER_1K_TOKENS", "0.002")
    summarizer = providers.MockSummarizer()

    result = asyncio.run(summarizer.generate(_student()))

    assert summarizer.estimate_max_cost(_student()) >= result.estimated_cost_usd
