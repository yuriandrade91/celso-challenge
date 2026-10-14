import time
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.dependencies import get_current_user
from app.database import Base, get_db
from app.interfaces.interfaces import INotifier
from app.main import app
from app.models import (
    AcademicTermModel,
    GradeReportModel,
    StudentModel,
    StudentNotificationModel,
)
from app.routers import terms as terms_router
from app.schemas.auth import AuthenticatedUser
from app.schemas.reports import AlunoCSV
from app.services.reports import hash_student_report

ANA = "0d2ccf31-8ed0-43a4-8554-18813dbdd001"
BRUNO = "0d2ccf31-8ed0-43a4-8554-18813dbdd002"
TEACHER = AuthenticatedUser(email="professor@example.com", role="teacher")
ANA_USER = AuthenticatedUser(email="ana@example.com", role="student", student_id=ANA)
BRUNO_USER = AuthenticatedUser(
    email="bruno@example.com", role="student", student_id=BRUNO
)
TERM = {
    "code": "2026.1",
    "name": "1.º semestre 2026",
    "startDate": "2026-02-01",
    "endDate": "2026-07-15",
}


class RecordingNotifier(INotifier):
    def __init__(self, failing: set[str] | None = None) -> None:
        self.sent: list[tuple[str, str]] = []
        self.failing = failing or set()

    async def send_notification(self, recipient: str, message: str) -> None:
        if recipient in self.failing:
            raise RuntimeError("smtp down")
        self.sent.append((recipient, message))


@pytest.fixture
def session_factory(monkeypatch: pytest.MonkeyPatch) -> Iterator[sessionmaker[Session]]:
    monkeypatch.setenv("GRADE_SUMMARY_PROVIDER", "mock")
    monkeypatch.setenv("GRADE_NOTIFICATION_PROVIDER", "mock")
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        db.add_all(
            [
                StudentModel(
                    student_id=ANA,
                    name="Ana Martins",
                    email="ana@example.com",
                    math_grade=17,
                    history_grade=8,
                    review_requested=False,
                ),
                StudentModel(
                    student_id=BRUNO,
                    name="Bruno Costa",
                    email="bruno@example.com",
                    math_grade=12,
                    history_grade=14,
                    review_requested=False,
                ),
            ]
        )
        db.commit()

    def override_db() -> Iterator[Session]:
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    yield factory
    app.dependency_overrides.clear()
    engine.dispose()


@pytest.fixture
def notifier(monkeypatch: pytest.MonkeyPatch) -> RecordingNotifier:
    recording = RecordingNotifier()
    monkeypatch.setattr(terms_router, "create_grade_report_notifier", lambda: recording)
    return recording


@pytest.fixture
def client(session_factory: sessionmaker[Session]) -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: TEACHER
    return TestClient(app, raise_server_exceptions=False)


def as_user(user: AuthenticatedUser) -> None:
    app.dependency_overrides[get_current_user] = lambda: user


def create_term(client: TestClient) -> int:
    response = client.post("/terms", json=TERM)
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


def test_term_crud_validates_dates_and_unique_code(client: TestClient) -> None:
    term_id = create_term(client)

    assert client.post("/terms", json=TERM).status_code == 409
    invalid = client.post("/terms", json={**TERM, "code": "x", "endDate": "2026-01-01"})
    assert invalid.status_code == 422

    updated = client.put(f"/terms/{term_id}", json={"endDate": "2026-07-31"})
    assert updated.status_code == 200
    assert updated.json()["data"]["endDate"] == "2026-07-31"
    assert client.put(f"/terms/{term_id}", json={"endDate": "2026-01-01"}).status_code == 409

    listed = client.get("/terms").json()["data"]
    assert [term["code"] for term in listed] == ["2026.1"]
    assert listed[0]["status"] == "open"
    assert listed[0]["entregas"]["alunosNotificados"] == 0

    assert client.delete(f"/terms/{term_id}").status_code == 200
    assert client.get("/terms").json()["data"] == []


def test_closing_term_notifies_each_student_once_with_personalised_summary(
    client: TestClient,
    session_factory: sessionmaker[Session],
    notifier: RecordingNotifier,
) -> None:
    term_id = create_term(client)

    response = client.post(f"/terms/{term_id}/close")

    assert response.status_code == 200, response.text
    report = response.json()["data"]
    assert report["totalAlunos"] == 2
    assert report["notificados"] == 2
    assert report["falhas"] == 0
    assert report["tokensGastos"] > 0
    assert {recipient for recipient, _ in notifier.sent} == {
        "ana@example.com",
        "bruno@example.com",
    }
    ana_email = next(message for to, message in notifier.sent if to == "ana@example.com")
    assert "Boletim de 1.º semestre 2026 (2026.1)" in ana_email
    assert "Atenção em História" in ana_email

    term = client.get("/terms").json()["data"][0]
    assert term["status"] == "closed"
    assert term["closedBy"] == TEACHER.email
    assert term["entregas"] == {
        "alunosNotificados": 2,
        "emailsPendentes": 0,
        "notificacoesLidas": 0,
    }
    deliveries = client.get(f"/terms/{term_id}/notifications").json()["data"]
    assert {item["emailStatus"] for item in deliveries} == {"sent"}
    assert {item["summarySource"] for item in deliveries} == {"llm"}

    # Fechar de novo não reenvia nem gasta tokens.
    again = client.post(f"/terms/{term_id}/close").json()["data"]
    assert again["jaNotificados"] == 2
    assert again["notificados"] == 0
    assert again["tokensGastos"] == 0
    assert len(notifier.sent) == 2
    assert client.put(f"/terms/{term_id}", json={"name": "x"}).status_code == 409
    assert client.delete(f"/terms/{term_id}").status_code == 409


def test_closing_reuses_summary_already_generated_for_the_same_grades(
    client: TestClient,
    session_factory: sessionmaker[Session],
    notifier: RecordingNotifier,
) -> None:
    ana = AlunoCSV(
        id_aluno=ANA,
        nome="Ana Martins",
        email="ana@example.com",
        nota_matematica=17,
        nota_historia=8,
    )
    with session_factory() as db:
        db.add(
            GradeReportModel(
                id_aluno=ANA,
                hash_notas=hash_student_report(ana),
                resumo_llm="Resumo já enviado pelo upload.",
                status_notificacao="sent",
            )
        )
        db.commit()
    term_id = create_term(client)

    report = client.post(f"/terms/{term_id}/close").json()["data"]

    assert report["notificados"] == 2
    assert report["resumosReaproveitados"] == 1
    sources = {
        item["studentId"]: item["summarySource"]
        for item in client.get(f"/terms/{term_id}/notifications").json()["data"]
    }
    assert sources == {ANA: "cache", BRUNO: "llm"}


def test_failed_email_keeps_in_app_notification_and_is_retried_on_next_close(
    client: TestClient,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flaky = RecordingNotifier(failing={"bruno@example.com"})
    monkeypatch.setattr(terms_router, "create_grade_report_notifier", lambda: flaky)
    term_id = create_term(client)

    first = client.post(f"/terms/{term_id}/close").json()["data"]
    assert first["notificados"] == 1
    assert first["falhas"] == 1
    assert "b***@example.com" in first["erros"][0]["mensagem"]
    assert client.get("/terms").json()["data"][0]["entregas"]["emailsPendentes"] == 1

    as_user(BRUNO_USER)
    inbox = client.get("/notifications/me").json()["data"]
    assert inbox["unreadCount"] == 1
    original_summary = inbox["items"][0]["summary"]

    as_user(TEACHER)
    flaky.failing.clear()
    retry = client.post(f"/terms/{term_id}/close").json()["data"]
    assert retry["notificados"] == 1
    assert retry["jaNotificados"] == 1
    assert retry["tokensGastos"] == 0  # reaproveita o texto já entregue na app
    assert flaky.sent[-1][0] == "bruno@example.com"
    assert original_summary in flaky.sent[-1][1]


def test_concurrent_close_is_rejected_while_lease_is_active(
    client: TestClient, session_factory: sessionmaker[Session], notifier: RecordingNotifier
) -> None:
    term_id = create_term(client)
    with session_factory() as db:
        term = db.get(AcademicTermModel, term_id)
        assert term is not None
        term.status = "closing"
        term.closing_owner = "another-execution"
        term.closing_until = int(time.time()) + 600
        db.commit()

    assert client.post(f"/terms/{term_id}/close").status_code == 409

    with session_factory() as db:
        term = db.get(AcademicTermModel, term_id)
        assert term is not None
        term.closing_until = int(time.time()) - 1  # o processo anterior caiu
        db.commit()
    assert client.post(f"/terms/{term_id}/close").json()["data"]["notificados"] == 2


def test_unexpected_error_releases_the_term(
    client: TestClient,
    session_factory: sessionmaker[Session],
    notifier: RecordingNotifier,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    term_id = create_term(client)

    def broken_roster(self: object) -> list[object]:
        raise RuntimeError("db down")

    monkeypatch.setattr(terms_router.TermRepository, "roster", broken_roster)
    assert client.post(f"/terms/{term_id}/close").status_code == 500
    assert client.get("/terms").json()["data"][0]["status"] == "open"


def test_close_unknown_term_returns_404(
    client: TestClient, notifier: RecordingNotifier
) -> None:
    assert client.post("/terms/999/close").status_code == 404
    assert client.get("/terms/999/notifications").status_code == 404


def test_student_inbox_is_private_and_supports_read_state(
    client: TestClient, notifier: RecordingNotifier
) -> None:
    term_id = create_term(client)
    client.post(f"/terms/{term_id}/close")

    assert client.get("/notifications/me").status_code == 403
    as_user(ANA_USER)
    inbox = client.get("/notifications/me").json()["data"]
    assert inbox["unreadCount"] == 1
    item = inbox["items"][0]
    assert item["kind"] == "term_report"
    assert item["termCode"] == "2026.1"
    assert item["title"] == "Boletim de 1.º semestre 2026"
    assert item["mathGrade"] == 17

    as_user(BRUNO_USER)
    assert client.patch(f"/notifications/{item['id']}/read").status_code == 404

    as_user(ANA_USER)
    assert client.patch(f"/notifications/{item['id']}/read").status_code == 200
    assert client.get("/notifications/me").json()["data"]["unreadCount"] == 0

    as_user(BRUNO_USER)
    assert client.post("/notifications/me/read-all").json()["data"] == 1
    assert client.get("/notifications/me").json()["data"]["unreadCount"] == 0
    as_user(TEACHER)
    assert client.get("/terms").json()["data"][0]["entregas"]["notificacoesLidas"] == 2


@pytest.mark.parametrize(
    ("decision", "title", "grade"),
    [
        (
            {"action": "adjusted", "teacherResponse": "Revi a questão 3.", "adjustedGrade": 11},
            "Nota de História revista: 8 → 11",
            11,
        ),
        (
            {"action": "cancelled", "teacherResponse": "A correção está certa."},
            "Pedido de revisão de História encerrado",
            8,
        ),
    ],
)
def test_review_decision_notifies_the_student(
    client: TestClient,
    session_factory: sessionmaker[Session],
    decision: dict[str, object],
    title: str,
    grade: float,
) -> None:
    as_user(ANA_USER)
    review = client.post(
        "/reviews/",
        json={"subject": "history", "justification": "Acho que a questão 3 está certa."},
    )
    assert review.status_code == 201, review.text
    assert client.get("/notifications/me").json()["data"]["unreadCount"] == 0

    as_user(TEACHER)
    review_id = review.json()["data"]["id"]
    assert client.patch(f"/reviews/{review_id}/decision", json=decision).status_code == 200

    as_user(ANA_USER)
    inbox = client.get("/notifications/me").json()["data"]
    assert inbox["unreadCount"] == 1
    item = inbox["items"][0]
    assert item["kind"] == "review_decision"
    assert item["reviewId"] == review_id
    assert item["termId"] is None
    assert item["title"] == title
    assert item["historyGrade"] == grade
    assert str(decision["teacherResponse"]) in item["summary"]
    with session_factory() as db:
        stored = db.scalar(select(StudentNotificationModel))
        assert stored is not None and stored.email_status == "sent"


def test_review_decision_survives_email_failure(
    client: TestClient,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.notifications import MockStudentNotifier

    def down(self: object, recipient: str, message: str) -> None:
        raise RuntimeError("smtp down")

    as_user(ANA_USER)
    review_id = client.post(
        "/reviews/",
        json={"subject": "math", "justification": "Gostaria de rever a prova."},
    ).json()["data"]["id"]
    monkeypatch.setattr(MockStudentNotifier, "send_notification", down)

    as_user(TEACHER)
    response = client.patch(
        f"/reviews/{review_id}/decision",
        json={"action": "adjusted", "teacherResponse": "Ajustado.", "adjustedGrade": 18},
    )

    assert response.status_code == 200
    with session_factory() as db:
        stored = db.scalar(select(StudentNotificationModel))
        assert stored is not None
        assert stored.email_status == "failed"
        assert stored.title == "Nota de Matemática revista: 17 → 18"


def test_legacy_notifications_table_is_rebuilt_keeping_rows() -> None:
    from sqlalchemy import inspect, text

    from app.database import rebuild_legacy_notifications

    engine = create_engine("sqlite://", poolclass=StaticPool)
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE student_notifications (id INTEGER PRIMARY KEY, "
                "student_id VARCHAR NOT NULL, term_id INTEGER NOT NULL, "
                "kind VARCHAR(32) NOT NULL, title VARCHAR(200) NOT NULL, "
                "summary TEXT NOT NULL, math_grade FLOAT NOT NULL, "
                "history_grade FLOAT NOT NULL, summary_source VARCHAR(16) NOT NULL, "
                "tokens INTEGER NOT NULL, email_status VARCHAR(16) NOT NULL, "
                "read_at DATETIME, created_at DATETIME NOT NULL)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX ix_student_notifications_term_id "
                "ON student_notifications (term_id)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO student_notifications VALUES (1, 's', 1, 'term_report', "
                "'t', 'resumo', 10, 11, 'llm', 5, 'sent', NULL, '2026-10-14')"
            )
        )

        rebuild_legacy_notifications(connection)
        rebuild_legacy_notifications(connection)  # idempotente

        columns = {c["name"]: c for c in inspect(connection).get_columns("student_notifications")}
        assert columns["term_id"]["nullable"] is True
        assert "review_id" in columns
        assert connection.execute(
            text("SELECT summary FROM student_notifications")
        ).scalar_one() == "resumo"
        connection.execute(
            text(
                "INSERT INTO student_notifications (student_id, kind, review_id, title, "
                "summary, math_grade, history_grade, tokens, email_status, created_at) "
                "VALUES ('s', 'review_decision', 7, 't', 'b', 1, 2, 0, 'sent', '2026-10-14')"
            )
        )
    engine.dispose()


def test_notification_timestamps_are_serialised_as_utc(
    client: TestClient, notifier: RecordingNotifier
) -> None:
    term_id = create_term(client)
    client.post(f"/terms/{term_id}/close")

    term = client.get("/terms").json()["data"][0]
    assert term["createdAt"].endswith("Z")
    assert term["closedAt"].endswith("Z")
    as_user(ANA_USER)
    item = client.get("/notifications/me").json()["data"]["items"][0]
    assert item["createdAt"].endswith("Z")
    client.patch(f"/notifications/{item['id']}/read")
    assert client.get("/notifications/me").json()["data"]["items"][0]["readAt"].endswith(
        "Z"
    )
