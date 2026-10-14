from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.errors import install_error_handlers
from app.auth.dependencies import get_current_user
from app.database import Base, get_db, rebuild_legacy_notifications
from app.models import StudentModel, StudentNotificationModel
from app.routers.students import router as students_router
from app.schemas.auth import AuthenticatedUser

STUDENT_ID = "0d2ccf31-8ed0-43a4-8554-18813dbdd001"


@pytest.fixture
def client() -> Iterator[TestClient]:
    engine: Engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as db:
        db.add(
            StudentModel(
                student_id=STUDENT_ID,
                name="Ana Martins",
                email="ana.martins@example.com",
                math_grade=17,
                history_grade=15,
                review_requested=False,
            )
        )
        db.commit()

    app = FastAPI()
    install_error_handlers(app)
    app.include_router(students_router)
    app.state.session_factory = session_factory

    def override_db() -> Iterator[Session]:
        with session_factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        email="professor@example.com", role="teacher"
    )
    with TestClient(app) as test_client:
        yield test_client
    engine.dispose()


def test_teacher_updates_grade_without_review_change(client: TestClient) -> None:
    response = client.put(f"/students/{STUDENT_ID}", json={"mathGrade": 9})

    assert response.status_code == 200
    assert response.json()["data"]["mathGrade"] == 9
    assert client.get(f"/students/{STUDENT_ID}").json()["data"]["mathGrade"] == 9


def test_teacher_update_that_starts_a_review_returns_the_student(
    client: TestClient,
) -> None:
    response = client.put(
        f"/students/{STUDENT_ID}", json={"reviewRequested": True}
    )

    assert response.status_code == 200
    assert response.json()["data"]["reviewRequested"] is True


@pytest.mark.parametrize("grade", [-1, 20.5, 25])
def test_student_grades_must_stay_between_zero_and_twenty(
    client: TestClient, grade: float
) -> None:
    updated = client.put(f"/students/{STUDENT_ID}", json={"mathGrade": grade})
    created = client.post(
        "/students/",
        json={
            "name": "Bruno Costa",
            "email": "bruno.costa@example.com",
            "mathGrade": grade,
            "historyGrade": 10,
        },
    )

    assert updated.status_code == 422
    assert created.status_code == 422
    assert client.get(f"/students/{STUDENT_ID}").json()["data"]["mathGrade"] == 17


def test_update_unknown_student_returns_not_found(client: TestClient) -> None:
    response = client.put(
        "/students/0d2ccf31-8ed0-43a4-8554-18813dbdd999", json={"mathGrade": 9}
    )

    assert response.status_code == 404


def stored_notifications(client: TestClient) -> list[StudentNotificationModel]:
    with client.app.state.session_factory() as db:
        return list(db.scalars(select(StudentNotificationModel)))


def test_grade_edit_notifies_the_student_with_the_new_grades(
    client: TestClient,
) -> None:
    response = client.put(
        f"/students/{STUDENT_ID}", json={"mathGrade": 18.5, "historyGrade": 15}
    )

    assert response.status_code == 200
    [notification] = stored_notifications(client)
    assert notification.student_id == STUDENT_ID
    assert notification.kind == "grade_update"
    # Só a nota que mudou entra no título; o MockStudentNotifier confirma o email.
    assert notification.title == "Nota de Matemática atualizada: 17 → 18.5"
    assert "Matemática: 17 → 18.5/20" in notification.summary
    assert "História" not in notification.summary
    assert (notification.math_grade, notification.history_grade) == (18.5, 15)
    assert notification.email_status == "sent"
    assert notification.read_at is None


@pytest.mark.parametrize(
    "payload",
    [{"mathGrade": 17, "historyGrade": 15}, {"reviewRequested": True}],
)
def test_update_without_grade_change_does_not_notify(
    client: TestClient, payload: dict[str, object]
) -> None:
    assert client.put(f"/students/{STUDENT_ID}", json=payload).status_code == 200

    assert stored_notifications(client) == []


def test_notifications_table_without_grade_update_kind_is_rebuilt() -> None:
    engine = create_engine("sqlite://", poolclass=StaticPool)
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE student_notifications (id INTEGER PRIMARY KEY, "
                "student_id VARCHAR NOT NULL, kind VARCHAR(32) NOT NULL, "
                "term_id INTEGER, review_id INTEGER, title VARCHAR(200) NOT NULL, "
                "summary TEXT NOT NULL, math_grade FLOAT NOT NULL, "
                "history_grade FLOAT NOT NULL, summary_source VARCHAR(16), "
                "tokens INTEGER NOT NULL, email_status VARCHAR(16) NOT NULL, "
                "read_at DATETIME, created_at DATETIME NOT NULL, "
                "CONSTRAINT ck_student_notifications_kind "
                "CHECK (kind IN ('term_report', 'review_decision')))"
            )
        )
        connection.execute(
            text(
                "INSERT INTO student_notifications VALUES (1, 's', 'review_decision', "
                "NULL, 7, 't', 'resposta', 10, 11, NULL, 0, 'sent', NULL, '2026-10-14')"
            )
        )

        rebuild_legacy_notifications(connection)
        rebuild_legacy_notifications(connection)  # idempotente

        assert "review_id" in {
            c["name"] for c in inspect(connection).get_columns("student_notifications")
        }
        assert connection.execute(
            text("SELECT review_id, summary FROM student_notifications")
        ).one() == (7, "resposta")
        connection.execute(
            text(
                "INSERT INTO student_notifications (student_id, kind, title, summary, "
                "math_grade, history_grade, tokens, email_status, created_at) "
                "VALUES ('s', 'grade_update', 't', 'b', 1, 2, 0, 'sent', '2026-10-14')"
            )
        )
    engine.dispose()
