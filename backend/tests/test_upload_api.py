from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.dependencies import get_current_user
from app.database import Base, get_db, get_session_factory
from app.main import app
from app.models import GradeReportExecutionModel, GradeReportModel, StudentModel
from app.schemas.auth import AuthenticatedUser

HEADER = "id_aluno,nome,email,nota_matematica,nota_historia\n"
ANA = "0d2ccf31-8ed0-43a4-8554-18813dbdd001"
CSV = (
    HEADER
    + f"{ANA},Ana Martins,ana.martins@example.com,17,15\n"
    + "0d2ccf31-8ed0-43a4-8554-18813dbdd002,Bruno Costa,bruno.costa@example.com,8,12\n"
    + "0d2ccf31-8ed0-43a4-8554-18813dbdd003,Carla Nunes,carla.nunes@example.com,22,14\n"
    + f"{ANA},Ana Martins,ana.martins@example.com,17,15\n"
).encode()
TEACHER = AuthenticatedUser(email="professor@example.com", role="teacher")


@pytest.fixture
def session_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[sessionmaker[Session]]:
    monkeypatch.setenv("GRADE_SUMMARY_PROVIDER", "mock")
    monkeypatch.setenv("GRADE_NOTIFICATION_PROVIDER", "mock")
    monkeypatch.setenv("GRADE_MAX_CONCURRENCY", "5")
    monkeypatch.setenv("GRADE_MAX_UPLOAD_SIZE_MB", "10")
    monkeypatch.setenv("LLM_INPUT_USD_PER_1K_TOKENS", "0.00015")
    monkeypatch.setenv("LLM_OUTPUT_USD_PER_1K_TOKENS", "0.0006")
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db() -> Iterator[Session]:
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_session_factory] = lambda: factory
    yield factory
    app.dependency_overrides.clear()
    engine.dispose()


@pytest.fixture
def client(session_factory: sessionmaker[Session]) -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: TEACHER
    # Sem `with`: o lifespan (banco real e contas de arranque) não é executado.
    return TestClient(app)


def _upload(client: TestClient, content: bytes, filename: str = "notas.csv"):
    return client.post("/upload", files={"file": (filename, content, "text/csv")})


def test_upload_processes_reports_and_persists_execution(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    response = _upload(client, CSV)

    assert response.status_code == 200
    assert response.headers["X-Request-ID"]
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    assert data["totalLinhas"] == 4
    assert data["processados"] == 2
    assert data["falhasValidacao"] == 1
    assert data["duplicadosIgnorados"] == 1
    assert data["tokensGastos"] > 0
    assert data["custoEstimadoUsd"] > 0
    assert data["tempoMedioProcessamentoMs"] > 0
    assert data["erros"] == [
        {
            "linha": 4,
            "campo": "nota_matematica",
            "mensagem": "Input should be less than or equal to 20",
        }
    ]
    with session_factory() as db:
        execution = db.scalar(select(GradeReportExecutionModel))
        assert execution.execution_id == data["executionId"]
        assert execution.duplicados_ignorados == 1
        assert execution.falhas_validacao == 1
        statuses = db.scalars(select(GradeReportModel.status_notificacao)).all()
        assert statuses == ["sent", "sent"]
        assert db.get(StudentModel, ANA).math_grade == 17


def test_reupload_is_served_from_cache_without_tokens(client: TestClient) -> None:
    _upload(client, CSV)

    data = _upload(client, CSV).json()["data"]

    assert data["processados"] == 0
    assert data["ignoradosCache"] == 2
    assert data["tokensGastos"] == 0
    assert data["custoEstimadoUsd"] == 0


@pytest.mark.parametrize(
    ("content", "filename", "status", "message"),
    [
        (b"x", "notas.txt", 400, "Apenas CSV"),
        (b"", "notas.csv", 400, "não contém um CSV válido"),
        (b"\xff\xfe\x00bad", "notas.csv", 400, "UTF-8"),
    ],
)
def test_upload_rejects_invalid_files_with_error_envelope(
    client: TestClient, content: bytes, filename: str, status: int, message: str
) -> None:
    response = _upload(client, content, filename)

    assert response.status_code == status
    body = response.json()
    assert body["success"] is False
    assert message in body["errors"][0]["message"]


def test_upload_enforces_size_limit(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GRADE_MAX_UPLOAD_SIZE_MB", "1")

    response = _upload(client, HEADER.encode() + b"x" * (1024 * 1024))

    assert response.status_code == 413


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("GRADE_MAX_CONCURRENCY", "0"),
        ("GRADE_SUMMARY_PROVIDER", "unknown"),
        ("GRADE_SUMMARY_FALLBACK", "maybe"),
    ],
)
def test_server_misconfiguration_is_reported_as_503(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)

    response = _upload(client, CSV)

    assert response.status_code == 503
    assert name in response.json()["errors"][0]["message"]


def test_upload_requires_teacher(session_factory: sessionmaker[Session]) -> None:
    client = TestClient(app)
    assert _upload(client, CSV).status_code == 401

    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        email="ana.martins@example.com", role="student", student_id=ANA
    )
    assert _upload(client, CSV).status_code == 403


def test_upload_is_rate_limited_per_teacher(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UPLOAD_RATE_LIMIT_PER_MINUTE", "2")

    statuses = [_upload(client, CSV).status_code for _ in range(3)]

    assert statuses == [200, 200, 429]


def test_async_upload_returns_202_and_is_trackable(
    session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    import time
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def no_lifespan(_app):
        yield

    # O cliente com `with` mantém o loop vivo para a tarefa em segundo plano;
    # o lifespan real (banco e contas de arranque) é substituído.
    monkeypatch.setattr(app.router, "lifespan_context", no_lifespan)
    app.dependency_overrides[get_current_user] = lambda: TEACHER

    with TestClient(app) as client:
        accepted = client.post(
            "/upload?mode=async",
            files={"file": ("notas.csv", CSV, "text/csv")},
        )
        assert accepted.status_code == 202
        execution_id = accepted.json()["data"]["executionId"]
        assert accepted.headers["Location"] == f"/executions/{execution_id}"

        for _ in range(100):
            execution = client.get(f"/executions/{execution_id}").json()["data"]
            if execution["status"] != "running":
                break
            time.sleep(0.02)

    assert execution["status"] == "completed"
    assert execution["processados"] == 2
    assert execution["falhasValidacao"] == 1


def test_async_upload_with_invalid_csv_marks_execution_failed(
    session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    import time
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def no_lifespan(_app):
        yield

    monkeypatch.setattr(app.router, "lifespan_context", no_lifespan)
    app.dependency_overrides[get_current_user] = lambda: TEACHER

    with TestClient(app) as client:
        accepted = client.post(
            "/upload?mode=async", files={"file": ("notas.csv", b"", "text/csv")}
        )
        execution_id = accepted.json()["data"]["executionId"]
        for _ in range(100):
            execution = client.get(f"/executions/{execution_id}").json()["data"]
            if execution["status"] != "running":
                break
            time.sleep(0.02)

    assert execution["status"] == "failed"
    assert "CSV válido" in execution["erro"]


def test_execution_history_and_summary(client: TestClient) -> None:
    _upload(client, CSV)
    _upload(client, CSV)

    history = client.get("/executions?limit=10").json()["data"]
    dispatcher = client.get("/metrics?recent=0").json()["data"]["dispatcher"]

    assert len(history) == 2
    assert history[0]["ignoradosCache"] == 2  # mais recente primeiro
    assert dispatcher["execucoes"] == 2
    assert dispatcher["alunosProcessados"] == 2
    assert dispatcher["ignoradosCache"] == 2
    assert dispatcher["taxaFalhaProcessamento"] == 0
    assert dispatcher["custoMedioPorAlunoUsd"] > 0
    assert client.get("/executions/summary").status_code == 404
    assert client.get("/executions/desconhecida").status_code == 404


def test_metrics_endpoint_combines_dispatcher_operational_and_recent(
    client: TestClient,
) -> None:
    _upload(client, CSV)
    _upload(client, CSV)

    response = client.get("/metrics?recent=1")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["totalAlunosProcessados"] == 2
    dispatcher = data["dispatcher"]
    # As quatro métricas pedidas pela opção 2 do desafio.
    assert dispatcher["alunosProcessados"] == 2
    assert dispatcher["falhas"] == 2  # uma linha inválida em cada upload
    assert dispatcher["custoEstimadoUsd"] > 0
    assert dispatcher["tempoMedioProcessamentoMs"] > 0
    assert dispatcher["taxaCache"] == 0.5  # 2 enviados, 2 servidos do cache
    assert dispatcher["linhasRecebidas"] == 8
    assert dispatcher["tempoMedioPipelineMs"] > 0
    assert dispatcher["ultimaExecucaoEm"] is not None
    operational = data["operacional"]
    assert operational["notificacoesEnviadas"] == 2
    assert operational["httpRequisicoes"] >= 2
    assert operational["httpErros5xx"] == 0
    assert operational["circuitoLlm"] == {"estado": "closed", "falhasConsecutivas": 0}
    assert len(data["ultimasExecucoes"]) == 1


def test_metrics_endpoint_is_teacher_only(
    session_factory: sessionmaker[Session],
) -> None:
    client = TestClient(app)
    assert client.get("/metrics").status_code == 401
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        email="ana.martins@example.com", role="student", student_id=ANA
    )
    assert client.get("/metrics").status_code == 403
