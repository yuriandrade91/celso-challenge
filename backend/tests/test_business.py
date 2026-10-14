import asyncio

from pydantic import ValidationError
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.interfaces.interfaces import (
    INotifier,
    ISummarizer,
    IGradeReportRepository,
    StoredGradeReport,
    SummaryResult,
)
from app.models import GradeReportExecutionModel
from app.repositories.reports import ReportRepository
from app.schemas.reports import AlunoCSV, UploadReport
from app.services.reports import (
    hash_grades,
    hash_student_report,
    process_csv,
)


def test_student_csv_row_validates_required_fields() -> None:
    student = AlunoCSV.model_validate(
        {
            "id_aluno": "7f3c2a10-4b8e-4e21-9d55-0c6a1b2e9f01",
            "nome": "Maria Souza",
            "email": "maria@example.com",
            "nota_matematica": "17.5",
            "nota_historia": "14",
        }
    )

    assert student.nota_matematica == 17.5
    assert student.nota_historia == 14


def test_student_csv_row_rejects_invalid_grade() -> None:
    with pytest.raises(ValidationError):
        AlunoCSV.model_validate(
            {
                "id_aluno": "7f3c2a10-4b8e-4e21-9d55-0c6a1b2e9f01",
                "nome": "Maria Souza",
                "email": "maria@example.com",
                "nota_matematica": "21",
                "nota_historia": "14",
            }
        )


def test_grade_hash_is_deterministic_and_changes_with_grades() -> None:
    first_hash = hash_grades(17.5, 14)

    assert first_hash == hash_grades(17.5, 14)
    assert hash_grades(17, 14) == hash_grades(17.0, 14.0)
    assert first_hash != hash_grades(17.5, 13)


def test_report_hash_includes_student_identity() -> None:
    student = AlunoCSV.model_validate(
        {
            "id_aluno": "7f3c2a10-4b8e-4e21-9d55-0c6a1b2e9f01",
            "nome": "Maria Souza",
            "email": "maria@example.com",
            "nota_matematica": "17.5",
            "nota_historia": "14",
        }
    )
    renamed = student.model_copy(update={"nome": "Maria Silva"})
    new_email = student.model_copy(update={"email": "maria.silva@example.com"})

    assert hash_student_report(student) != hash_student_report(renamed)
    assert hash_student_report(student) != hash_student_report(new_email)


class MemoryReportRepository(IGradeReportRepository):
    def __init__(self) -> None:
        self.reports: dict[str, StoredGradeReport] = {}
        self.roster: dict[str, AlunoCSV] = {}
        self.claims: dict[str, str] = {}

    def get_report(self, student_id: str) -> StoredGradeReport | None:
        return self.reports.get(student_id)

    def save_report(
        self, student: AlunoCSV, grades_hash: str, summary: str, tokens: int
    ) -> bool:
        updated = student.id_aluno in self.reports
        self.reports[student.id_aluno] = StoredGradeReport(
            grades_hash, summary, tokens, "pending"
        )
        return updated

    def upsert_student(self, student: AlunoCSV) -> None:
        self.roster[student.id_aluno] = student

    def claim_report(self, student_id: str, owner: str, lease_seconds: int) -> bool:
        holder = self.claims.get(student_id)
        if holder not in (None, owner):
            return False
        self.claims[student_id] = owner
        return True

    def release_report(self, student_id: str, owner: str) -> None:
        if self.claims.get(student_id) == owner:
            del self.claims[student_id]

    def mark_report_notified(self, student_id: str) -> None:
        report = self.reports[student_id]
        self.reports[student_id] = StoredGradeReport(
            report.grades_hash,
            report.summary,
            report.tokens,
            "sent",
        )


class FakeSummarizer(ISummarizer):
    def __init__(self) -> None:
        self.calls = 0

    @property
    def provider_name(self) -> str:
        return "test"

    async def generate(self, student: AlunoCSV) -> SummaryResult:
        self.calls += 1
        return SummaryResult(
            f"Resumo de {student.nome}", 10, 5, 0.00025
        )


class FakeNotifier(INotifier):
    def __init__(self, failures: int = 0) -> None:
        self.failures = failures
        self.deliveries: list[tuple[str, str]] = []

    @property
    def provider_name(self) -> str:
        return "test"

    async def send_notification(self, recipient: str, message: str) -> None:
        self.deliveries.append((recipient, message))
        if self.failures:
            self.failures -= 1
            raise RuntimeError("temporary transport failure")


def _csv(*rows: str) -> bytes:
    header = "id_aluno,nome,email,nota_matematica,nota_historia"
    return (header + "\n" + "\n".join(rows) + "\n").encode()


def test_process_csv_validates_deduplicates_and_caches_delivery() -> None:
    student_id = "7f3c2a10-4b8e-4e21-9d55-0c6a1b2e9f01"
    content = _csv(
        f"{student_id},Maria Souza,maria@example.com,17.5,14",
        "7f3c2a10-4b8e-4e21-9d55-0c6a1b2e9f02,Joao,joao@example.com,21,14",
        f"{student_id},Maria Souza,maria@example.com,17.5,14",
        "7f3c2a10-4b8e-4e21-9d55-0c6a1b2e9f03,Maria Souza,"
        "MARIA@example.com,17,14",
    )
    repository = MemoryReportRepository()
    notifier = FakeNotifier()
    summarizer = FakeSummarizer()

    first = asyncio.run(process_csv(content, repository, notifier, summarizer))
    second = asyncio.run(process_csv(content, repository, notifier, summarizer))

    assert first.total_linhas == 4
    assert first.processados == 1
    assert first.falhas_validacao == 1
    assert first.duplicados_ignorados == 2
    assert first.tokens_gastos == 15
    assert first.custo_estimado_usd == 0.00025
    assert first.tempo_total_ms > 0
    assert second.ignorados_cache == 1
    assert second.processados == 0
    assert summarizer.calls == 1
    assert len(notifier.deliveries) == 1


def test_process_csv_reports_missing_required_columns() -> None:
    report = asyncio.run(
        process_csv(
            b"id_aluno,nome\nstudent-1,Maria Souza\n",
            MemoryReportRepository(),
            FakeNotifier(),
            FakeSummarizer(),
        )
    )

    assert report.falhas == 1
    assert report.falhas_validacao == 1
    assert {
        issue.campo for issue in report.erros
    } == {"email", "nota_matematica", "nota_historia"}


def test_failed_delivery_retries_without_regenerating_or_recharging() -> None:
    student_id = "7f3c2a10-4b8e-4e21-9d55-0c6a1b2e9f01"
    content = _csv(
        f"{student_id},Maria Souza,maria@example.com,17.5,14"
    )
    repository = MemoryReportRepository()
    notifier = FakeNotifier(failures=1)
    summarizer = FakeSummarizer()

    failed = asyncio.run(process_csv(content, repository, notifier, summarizer))
    recovered = asyncio.run(
        process_csv(content, repository, notifier, summarizer)
    )

    assert failed.falhas_processamento == 1
    assert failed.tokens_gastos == 15
    assert repository.reports[student_id].notification_status == "sent"
    assert recovered.processados == 1
    assert recovered.tokens_gastos == 0
    assert recovered.custo_estimado_usd == 0
    assert summarizer.calls == 1
    assert len(notifier.deliveries) == 2


def test_processing_concurrency_is_bounded_by_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    class TrackingSummarizer(FakeSummarizer):
        active = 0
        peak = 0

        async def generate(self, student: AlunoCSV) -> SummaryResult:
            self.active += 1
            self.peak = max(self.peak, self.active)
            await asyncio.sleep(0.01)
            self.active -= 1
            return await super().generate(student)

    monkeypatch.setenv("GRADE_MAX_CONCURRENCY", "2")
    rows = [
        f"7f3c2a10-4b8e-4e21-9d55-0c6a1b2e9f{i:02d},Student {i},"
        f"student{i}@example.com,17,14"
        for i in range(1, 8)
    ]
    summarizer = TrackingSummarizer()

    report = asyncio.run(
        process_csv(
            _csv(*rows),
            MemoryReportRepository(),
            FakeNotifier(),
            summarizer,
        )
    )

    assert report.processados == 7
    assert summarizer.peak == 2


def test_report_repository_persists_delivery_state_and_execution_metrics() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    student = AlunoCSV.model_validate(
        {
            "id_aluno": "7f3c2a10-4b8e-4e21-9d55-0c6a1b2e9f01",
            "nome": "Maria Souza",
            "email": "maria@example.com",
            "nota_matematica": "17.5",
            "nota_historia": "14",
        }
    )

    with Session(engine) as db:
        repository = ReportRepository(db)
        grades_hash = hash_grades(17.5, 14)
        repository.save_report(student, grades_hash, "Resumo", 15)
        pending = repository.get_report(student.id_aluno)
        repository.mark_report_notified(student.id_aluno)
        report = UploadReport(
            total_linhas=1,
            processados=1,
            tokens_gastos=15,
            custo_estimado_usd=0.00025,
            tempo_total_ms=12,
            tempo_medio_processamento_ms=12,
        )
        repository.record_execution(
            report,
            summary_provider="test",
            notification_provider="test",
        )

        assert pending is not None
        assert pending.notification_status == "pending"
        assert repository.get_report(student.id_aluno).notification_status == "sent"
        execution = db.scalar(select(GradeReportExecutionModel))
        assert execution is not None
        assert execution.processados == 1
        assert execution.tokens_gastos == 15
        assert execution.custo_estimado_usd == 0.00025
        assert execution.fallbacks_llm == 0

    engine.dispose()


def test_llm_outage_degrades_to_template_and_still_notifies() -> None:
    from app.services.providers import (
        FallbackSummarizer,
        ProviderCircuitOpenError,
        TemplateSummarizer,
    )

    class DownSummarizer(FakeSummarizer):
        async def generate(self, student: AlunoCSV) -> SummaryResult:
            raise ProviderCircuitOpenError("circuit open")

    content = _csv(
        "7f3c2a10-4b8e-4e21-9d55-0c6a1b2e9f01,Maria Souza,maria@example.com,17.5,8"
    )
    notifier = FakeNotifier()

    report = asyncio.run(
        process_csv(
            content,
            MemoryReportRepository(),
            notifier,
            FallbackSummarizer(DownSummarizer(), TemplateSummarizer()),
        )
    )

    assert report.processados == 1
    assert report.falhas == 0
    assert report.fallbacks_llm == 1
    assert report.tokens_gastos == 0
    assert "Atenção em História" in notifier.deliveries[0][1]


def test_notification_contains_grades_and_summary() -> None:
    content = _csv(
        "7f3c2a10-4b8e-4e21-9d55-0c6a1b2e9f01,Maria Souza,maria@example.com,17.5,14"
    )
    notifier = FakeNotifier()

    report = asyncio.run(
        process_csv(content, MemoryReportRepository(), notifier, FakeSummarizer())
    )

    message = notifier.deliveries[0][1]
    assert report.execution_id
    assert "Matemática: 17.5/20" in message
    assert "História: 14/20" in message
    assert "Resumo de Maria Souza" in message


def test_percentile_uses_nearest_rank() -> None:
    from app.services.reports import _percentile

    assert _percentile([], 95) == 0
    assert _percentile([5], 95) == 5
    assert _percentile(list(range(1, 101)), 95) == 95
    assert _percentile([10, 1, 3], 50) == 3


def test_average_time_is_per_student_not_total_divided_by_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SlowSummarizer(FakeSummarizer):
        async def generate(self, student: AlunoCSV) -> SummaryResult:
            await asyncio.sleep(0.05)
            return await super().generate(student)

    monkeypatch.setenv("GRADE_MAX_CONCURRENCY", "4")
    rows = [
        f"7f3c2a10-4b8e-4e21-9d55-0c6a1b2e9f{i:02d},Student {i},"
        f"student{i}@example.com,17,14"
        for i in range(1, 5)
    ]

    report = asyncio.run(
        process_csv(
            _csv(*rows), MemoryReportRepository(), FakeNotifier(), SlowSummarizer()
        )
    )

    # Em paralelo, cada aluno leva ~50 ms; total/N daria ~12 ms.
    assert report.tempo_medio_processamento_ms >= 45
    assert report.tempo_p95_processamento_ms >= report.tempo_medio_processamento_ms


def test_invalid_concurrency_is_a_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.domain.exceptions import ConfigurationError

    monkeypatch.setenv("GRADE_MAX_CONCURRENCY", "0")

    with pytest.raises(ConfigurationError):
        asyncio.run(
            process_csv(
                _csv(), MemoryReportRepository(), FakeNotifier(), FakeSummarizer()
            )
        )


def test_header_only_file_with_missing_columns_is_reported() -> None:
    report = asyncio.run(
        process_csv(
            b"id_aluno,nome\n",
            MemoryReportRepository(),
            FakeNotifier(),
            FakeSummarizer(),
        )
    )

    assert report.falhas_validacao == 1
    assert {issue.campo for issue in report.erros} == {
        "email",
        "nota_matematica",
        "nota_historia",
    }


@pytest.fixture
def report_db() -> Session:
    from app.models import StudentModel

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all(
            [
                StudentModel(
                    student_id="7f3c2a10-4b8e-4e21-9d55-0c6a1b2e9f01",
                    name="Maria Souza",
                    email="maria@example.com",
                    math_grade=10,
                    history_grade=10,
                    review_requested=False,
                ),
                StudentModel(
                    student_id="7f3c2a10-4b8e-4e21-9d55-0c6a1b2e9f07",
                    name="Rui Alves",
                    email="rui@example.com",
                    math_grade=11,
                    history_grade=11,
                    review_requested=False,
                ),
            ]
        )
        db.commit()
        yield db
    engine.dispose()


def test_upload_keeps_student_roster_in_sync(report_db: Session) -> None:
    from app.models import StudentModel

    content = _csv(
        "7f3c2a10-4b8e-4e21-9d55-0c6a1b2e9f01,Maria S. Souza,maria@example.com,12,8",
        "7f3c2a10-4b8e-4e21-9d55-0c6a1b2e9f02,Joao Lima,joao@example.com,15,16",
    )

    report = asyncio.run(
        process_csv(
            content, ReportRepository(report_db), FakeNotifier(), FakeSummarizer()
        )
    )

    maria = report_db.get(StudentModel, "7f3c2a10-4b8e-4e21-9d55-0c6a1b2e9f01")
    joao = report_db.get(StudentModel, "7f3c2a10-4b8e-4e21-9d55-0c6a1b2e9f02")
    assert report.processados == 2
    assert (maria.name, maria.math_grade, maria.history_grade) == (
        "Maria S. Souza",
        12,
        8,
    )
    assert joao is not None and joao.email == "joao@example.com"


@pytest.mark.parametrize(
    ("row", "expected_message"),
    [
        (
            "7f3c2a10-4b8e-4e21-9d55-0c6a1b2e9f01,Maria,rui@example.com,12,8",
            "pertence a outro aluno",
        ),
        (
            "7f3c2a10-4b8e-4e21-9d55-0c6a1b2e9f01,Maria,nova@example.com,12,8",
            "difere do cadastro",
        ),
    ],
)
def test_roster_conflicts_block_delivery(
    report_db: Session, row: str, expected_message: str
) -> None:
    from app.models import StudentModel

    notifier = FakeNotifier()

    report = asyncio.run(
        process_csv(
            _csv(row), ReportRepository(report_db), notifier, FakeSummarizer()
        )
    )

    assert report.falhas_processamento == 1
    assert expected_message in report.erros[0].mensagem
    assert notifier.deliveries == []
    maria = report_db.get(StudentModel, "7f3c2a10-4b8e-4e21-9d55-0c6a1b2e9f01")
    assert maria.math_grade == 10


def test_roster_matches_by_email_when_uuid_differs(report_db: Session) -> None:
    from app.models import StudentModel

    content = _csv(
        "7f3c2a10-4b8e-4e21-9d55-0c6a1b2e9f99,Maria Souza,maria@example.com,14,9"
    )

    report = asyncio.run(
        process_csv(
            content, ReportRepository(report_db), FakeNotifier(), FakeSummarizer()
        )
    )

    maria = report_db.get(StudentModel, "7f3c2a10-4b8e-4e21-9d55-0c6a1b2e9f01")
    assert report.processados == 1
    assert (maria.math_grade, maria.history_grade) == (14, 9)
    assert report_db.get(StudentModel, "7f3c2a10-4b8e-4e21-9d55-0c6a1b2e9f99") is None
