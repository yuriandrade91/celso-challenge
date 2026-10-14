import os
from pathlib import Path
from collections.abc import Generator
from importlib import import_module
from uuid import UUID, uuid4

from dotenv import load_dotenv
from sqlalchemy import Connection, create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, declarative_base, sessionmaker

DATABASE_PATH = Path(__file__).resolve().parents[1] / "backoffice.db"
load_dotenv(Path(__file__).resolve().parents[1] / ".env")
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DATABASE_PATH}")
database_url = make_url(DATABASE_URL)
if database_url.get_backend_name() != "sqlite":
    raise ValueError("Este backend requer uma DATABASE_URL SQLite.")
if database_url.database in (None, "", ":memory:"):
    raise ValueError("A DATABASE_URL SQLite precisa indicar um ficheiro.")

engine = create_engine(
    database_url,
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


# Migrações aditivas para bancos SQLite criados por versões anteriores.
_COLUMN_ADDITIONS: dict[str, dict[str, str]] = {
    "boletins": {
        "email": "TEXT",
        "nota_matematica": "FLOAT",
        "nota_historia": "FLOAT",
        "tokens_gastos": "INTEGER NOT NULL DEFAULT 0",
        "status_notificacao": "TEXT NOT NULL DEFAULT 'sent'",
        "processing_owner": "VARCHAR(32)",
        "processing_until": "INTEGER",
    },
    "grade_report_executions": {
        "execution_id": "VARCHAR(32)",
        "tempo_p95_processamento_ms": "FLOAT NOT NULL DEFAULT 0",
        "ignorados_cache": "INTEGER NOT NULL DEFAULT 0",
        "duplicados_ignorados": "INTEGER NOT NULL DEFAULT 0",
        "falhas_validacao": "INTEGER NOT NULL DEFAULT 0",
        "falhas_processamento": "INTEGER NOT NULL DEFAULT 0",
        "fallbacks_llm": "INTEGER NOT NULL DEFAULT 0",
        "em_processamento": "INTEGER NOT NULL DEFAULT 0",
        "orcamento_excedido": "BOOLEAN NOT NULL DEFAULT 0",
        "status": "VARCHAR(16) NOT NULL DEFAULT 'completed'",
        "erro": "TEXT",
    },
}


def rebuild_legacy_notifications(connection: Connection) -> None:
    """Recria student_notifications de versões anteriores do esquema.

    Cobre a primeira versão (term_id NOT NULL, sem review_id) e o CHECK de
    `kind` sem 'grade_update'. O SQLite não remove NOT NULL nem altera CHECK
    com ALTER TABLE; a tabela é refeita e as linhas existentes são copiadas.
    """
    from app.models import StudentNotificationModel

    inspector = inspect(connection)
    if "student_notifications" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("student_notifications")}
    table_sql = connection.execute(
        text(
            "SELECT sql FROM sqlite_master "
            "WHERE type = 'table' AND name = 'student_notifications'"
        )
    ).scalar_one()
    if "review_id" in columns and "grade_update" in table_sql:
        return
    copied_columns = ", ".join(
        column.name
        for column in StudentNotificationModel.__table__.columns
        if column.name in columns
    )
    connection.execute(
        text("ALTER TABLE student_notifications RENAME TO student_notifications_legacy")
    )
    # Os índices acompanham a tabela renomeada e colidiriam com os novos.
    for index in inspect(connection).get_indexes("student_notifications_legacy"):
        connection.execute(text(f'DROP INDEX IF EXISTS "{index["name"]}"'))
    StudentNotificationModel.__table__.create(connection)
    connection.execute(
        text(
            f"INSERT INTO student_notifications ({copied_columns}) "
            f"SELECT {copied_columns} FROM student_notifications_legacy"
        )
    )
    connection.execute(text("DROP TABLE student_notifications_legacy"))


def get_session_factory() -> sessionmaker[Session]:
    """Fábrica de sessões para trabalho fora do ciclo do pedido HTTP."""
    return SessionLocal


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def initialize_database() -> None:
    import_module("app.models")
    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        tables = set(inspect(connection).get_table_names())
        for table, additions in _COLUMN_ADDITIONS.items():
            if table not in tables:
                continue
            columns = {
                column["name"]
                for column in inspect(connection).get_columns(table)
            }
            for column, column_type in additions.items():
                if column not in columns:
                    connection.execute(
                        text(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")
                    )
        rebuild_legacy_notifications(connection)
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "ix_grade_report_executions_execution_id "
                "ON grade_report_executions (execution_id)"
            )
        )

        if {"students", "users"} <= tables:
            student_rows = connection.execute(
                text("SELECT student_id FROM students")
            ).scalars().all()
            student_id_mapping = {
                student_id: _canonical_uuid(student_id)
                for student_id in student_rows
            }
            for old_id, new_id in student_id_mapping.items():
                if old_id == new_id:
                    continue
                connection.execute(
                    text(
                        "UPDATE users SET student_id = :new_id "
                        "WHERE student_id = :old_id"
                    ),
                    {"old_id": old_id, "new_id": new_id},
                )
                connection.execute(
                    text(
                        "UPDATE students SET student_id = :new_id "
                        "WHERE student_id = :old_id"
                    ),
                    {"old_id": old_id, "new_id": new_id},
                )

            if "boletins" in tables:
                report_rows = connection.execute(
                    text("SELECT id_aluno FROM boletins")
                ).scalars().all()
                for old_id in report_rows:
                    new_id = student_id_mapping.get(old_id, _canonical_uuid(old_id))
                    if old_id != new_id:
                        connection.execute(
                            text(
                                "UPDATE boletins SET id_aluno = :new_id "
                                "WHERE id_aluno = :old_id"
                            ),
                            {"old_id": old_id, "new_id": new_id},
                        )

    from app.services.seed import sync_seed_students

    with SessionLocal() as db:
        sync_seed_students(db)

    from app.auth.service import bootstrap_accounts

    bootstrap_accounts(SessionLocal())


def _canonical_uuid(value: str) -> str:
    try:
        return str(UUID(value))
    except ValueError:
        return str(uuid4())
