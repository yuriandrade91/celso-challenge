import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.metrics import RUNTIME_METRICS
from app.models import GradeReportExecutionModel
from app.repositories.reports import ReportRepository
from app.services.dashboard import dashboard_metrics
from app.services.demo_metrics import seed_demo_runtime_metrics, sync_demo_executions


@pytest.fixture
def session_factory():
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


def count_executions(db) -> int:
    return db.scalar(select(func.count()).select_from(GradeReportExecutionModel))


def test_demo_history_is_seeded_once_and_feeds_the_dashboard(
    session_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ENABLE_DEMO_METRICS", "true")
    with session_factory() as db:
        db.add(
            GradeReportExecutionModel(
                execution_id="real0001", total_linhas=2, processados=2, falhas=0,
                tokens_gastos=10, custo_estimado_usd=0.001, tempo_total_ms=5,
                tempo_medio_processamento_ms=2, summary_provider="mock",
                notification_provider="mock",
            )
        )
        db.commit()
        sync_demo_executions(db)
        sync_demo_executions(db)  # idempotente entre arranques
        assert count_executions(db) == 9

        metrics = dashboard_metrics(ReportRepository(db), recent_limit=20)

    assert metrics.dados_emulados is True
    assert metrics.dispatcher.execucoes == 8  # 7 demo concluídas + 1 real
    assert metrics.dispatcher.alunos_processados == 478
    assert metrics.dispatcher.tokens_gastos > 0
    assert metrics.dispatcher.execucoes_com_orcamento_excedido == 1
    assert {e.status for e in metrics.ultimas_execucoes} == {"completed", "failed"}


def test_disabling_the_flag_removes_only_demo_rows(
    session_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ENABLE_DEMO_METRICS", "true")
    with session_factory() as db:
        sync_demo_executions(db)
        db.add(
            GradeReportExecutionModel(
                execution_id="real0001", total_linhas=1, processados=1, falhas=0,
                tokens_gastos=1, custo_estimado_usd=0, tempo_total_ms=1,
                tempo_medio_processamento_ms=1, summary_provider="mock",
                notification_provider="mock",
            )
        )
        db.commit()

        monkeypatch.setenv("ENABLE_DEMO_METRICS", "false")
        sync_demo_executions(db)

        assert db.scalars(select(GradeReportExecutionModel.execution_id)).all() == [
            "real0001"
        ]
        assert dashboard_metrics(ReportRepository(db)).dados_emulados is False


def test_runtime_counters_are_seeded_only_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_demo_runtime_metrics()
    assert RUNTIME_METRICS.snapshot()["http_requisicoes"] == 0

    monkeypatch.setenv("ENABLE_DEMO_METRICS", "true")
    seed_demo_runtime_metrics()
    snapshot = RUNTIME_METRICS.snapshot()

    assert snapshot["http_requisicoes"] == 480
    assert snapshot["http_erros_5xx"] == 4
    assert 0 < snapshot["http_latencia_p50_ms"] < snapshot["http_latencia_p95_ms"]
    assert snapshot["events"]["grade_report.provider.retry"] == 6
