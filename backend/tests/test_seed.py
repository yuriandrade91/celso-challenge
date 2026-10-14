from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.service import AuthService, _token_digest, bootstrap_accounts
from app.database import Base
from app.models import RefreshTokenModel, StudentModel, UserModel
from app.services.seed import sync_seed_students

FIRST_ID = "0d2ccf31-8ed0-43a4-8554-18813dbdd001"
SECOND_ID = "0d2ccf31-8ed0-43a4-8554-18813dbdd002"
MANUAL_ID = "0d2ccf31-8ed0-43a4-8554-18813dbdd005"


@pytest.fixture
def database() -> Iterator[tuple[sessionmaker[Session], Engine]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield sessionmaker(bind=engine, expire_on_commit=False), engine
    engine.dispose()


def test_seed_sync_updates_valid_unique_students_and_preserves_other_records(
    tmp_path: Path, database: tuple[sessionmaker[Session], Engine]
) -> None:
    session_factory, _engine = database
    csv_path = tmp_path / "students.csv"
    csv_path.write_text(
        "id_aluno,nome,email,nota_matematica,nota_historia\n"
        f"{FIRST_ID},Ana,ana@example.com,17,15\n"
        f"{SECOND_ID},Bruno,bruno@example.com,8,12\n"
        f"{FIRST_ID},Nome duplicado,ana@example.com,19,19\n"
        "0d2ccf31-8ed0-43a4-8554-18813dbdd003,Carla,"
        "carla@example.com,22,14\n",
        encoding="utf-8",
    )

    with session_factory() as db:
        sync_seed_students(db, csv_path)
        db.add(
            StudentModel(
                student_id=MANUAL_ID,
                name="Registo manual",
                email="manual@example.com",
                math_grade=10,
                history_grade=11,
                review_requested=False,
            )
        )
        db.commit()

    csv_path.write_text(
        "id_aluno,nome,email,nota_matematica,nota_historia\n"
        f"{FIRST_ID},Ana atualizada,ana@example.com,18,16\n"
        f"{SECOND_ID},Bruno atualizado,bruno@example.com,9,13\n",
        encoding="utf-8",
    )
    with session_factory() as db:
        sync_seed_students(db, csv_path)
        students = db.scalars(select(StudentModel)).all()
        by_id = {student.student_id: student for student in students}

    assert len(by_id) == 3
    assert by_id[FIRST_ID].name == "Ana atualizada"
    assert by_id[FIRST_ID].math_grade == 18
    assert by_id[SECOND_ID].name == "Bruno atualizado"
    assert MANUAL_ID in by_id


def test_bootstrap_accounts_tracks_seed_email_updates_and_revokes_old_sessions(
    monkeypatch: pytest.MonkeyPatch,
    database: tuple[sessionmaker[Session], Engine],
) -> None:
    session_factory, _engine = database
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-that-is-at-least-32-characters")
    monkeypatch.setenv("BOOTSTRAP_TEACHER_EMAIL", "teacher@example.com")
    monkeypatch.setenv("BOOTSTRAP_TEACHER_PASSWORD", "teacher-password-test")
    monkeypatch.setenv("BOOTSTRAP_STUDENT_PASSWORD", "student-password-test")
    monkeypatch.setenv("ENABLE_SWAGGER_DEMO_ACCOUNTS", "false")

    with session_factory() as db:
        db.add(
            StudentModel(
                student_id=FIRST_ID,
                name="Ana",
                email="new-ana@example.com",
                math_grade=17,
                history_grade=15,
                review_requested=False,
            )
        )
        db.add(
            UserModel(
                email="old-ana@example.com",
                password_hash="old-hash",
                role="student",
                student_id=FIRST_ID,
            )
        )
        db.add(
            RefreshTokenModel(
                token_hash=_token_digest("old-refresh-token"),
                user_email="old-ana@example.com",
                expires_at=2_000_000_000,
            )
        )
        db.commit()

    bootstrap_accounts(session_factory())

    with session_factory() as db:
        account = db.scalar(
            select(UserModel).where(UserModel.student_id == FIRST_ID)
        )
        old_token_count = db.scalar(
            select(func.count())
            .select_from(RefreshTokenModel)
            .where(RefreshTokenModel.user_email == "old-ana@example.com")
        )
        teacher = db.get(UserModel, "teacher@example.com")

    assert account is not None
    assert account.email == "new-ana@example.com"
    assert old_token_count == 0
    assert teacher is not None


def test_database_initialization_seeds_students_and_login_accounts(
    monkeypatch: pytest.MonkeyPatch,
    database: tuple[sessionmaker[Session], Engine],
) -> None:
    session_factory, engine = database
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-that-is-at-least-32-characters")
    monkeypatch.setenv("BOOTSTRAP_TEACHER_EMAIL", "teacher@example.com")
    monkeypatch.setenv("BOOTSTRAP_TEACHER_PASSWORD", "teacher-password-test")
    monkeypatch.setenv("BOOTSTRAP_STUDENT_PASSWORD", "student-password-test")
    monkeypatch.setenv("ENABLE_SWAGGER_DEMO_ACCOUNTS", "true")

    import app.database as database_module

    monkeypatch.setattr(database_module, "engine", engine)
    monkeypatch.setattr(database_module, "SessionLocal", session_factory)
    with session_factory() as db:
        db.add(
            StudentModel(
                student_id=MANUAL_ID,
                name="Registo manual",
                email="aaa@example.com",
                math_grade=10,
                history_grade=11,
                review_requested=False,
            )
        )
        db.commit()

    database_module.initialize_database()
    database_module.initialize_database()

    with session_factory() as db:
        student_count = db.scalar(select(func.count()).select_from(StudentModel))
        user_count = db.scalar(select(func.count()).select_from(UserModel))
        student_account_count = db.scalar(
            select(func.count())
            .select_from(UserModel)
            .where(UserModel.role == "student")
        )
        student_one = AuthService(db).login_demo_profile("aluno_1")
        student_two = AuthService(db).login_demo_profile("aluno_2")

    assert student_count == 4
    assert user_count == 5
    assert student_account_count == 4
    assert student_one.user.email == "ana.martins@example.com"
    assert student_two.user.email == "bruno.costa@example.com"


def test_database_initialization_reuses_existing_student_with_seed_email(
    monkeypatch: pytest.MonkeyPatch,
    database: tuple[sessionmaker[Session], Engine],
) -> None:
    session_factory, engine = database
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-that-is-at-least-32-characters")
    monkeypatch.setenv("BOOTSTRAP_TEACHER_EMAIL", "teacher@example.com")
    monkeypatch.setenv("BOOTSTRAP_TEACHER_PASSWORD", "teacher-password-test")
    monkeypatch.setenv("BOOTSTRAP_STUDENT_PASSWORD", "student-password-test")
    monkeypatch.setenv("ENABLE_SWAGGER_DEMO_ACCOUNTS", "true")

    legacy_id = "a8d9982b-5970-42d7-9dfd-d6bf325c5094"
    with session_factory() as db:
        db.add(
            StudentModel(
                student_id=legacy_id,
                name="Ana anterior",
                email="ana.martins@example.com",
                math_grade=10,
                history_grade=12,
                review_requested=False,
            )
        )
        db.add(
            UserModel(
                email="ana.martins@example.com",
                password_hash="legacy-hash",
                role="student",
                student_id=legacy_id,
            )
        )
        db.commit()

    import app.database as database_module

    monkeypatch.setattr(database_module, "engine", engine)
    monkeypatch.setattr(database_module, "SessionLocal", session_factory)
    database_module.initialize_database()

    with session_factory() as db:
        ana = db.get(StudentModel, legacy_id)
        accounts_for_ana = db.scalars(
            select(UserModel).where(
                UserModel.student_id == legacy_id,
                UserModel.role == "student",
            )
        ).all()
        first_demo_student = AuthService(db).login_demo_profile("aluno_1")

    assert ana is not None
    assert ana.name == "Ana Martins"
    assert ana.math_grade == 17
    assert accounts_for_ana[0].email == "ana.martins@example.com"
    assert len(accounts_for_ana) == 1
    assert first_demo_student.user.email == "ana.martins@example.com"
