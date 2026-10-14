import csv
import logging
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import StudentModel
from app.observability import log_event
from app.schemas.reports import AlunoCSV

logger = logging.getLogger(__name__)
SEED_FILE = Path(__file__).resolve().parents[2] / "notas_mock.csv"
REQUIRED_COLUMNS = {
    "id_aluno",
    "nome",
    "email",
    "nota_matematica",
    "nota_historia",
}


def load_seed_students(
    csv_path: Path = SEED_FILE,
) -> tuple[list[AlunoCSV], list[int], list[int]]:
    with csv_path.open(encoding="utf-8-sig", newline="") as seed_file:
        reader = csv.DictReader(seed_file)
        if reader.fieldnames is None or not REQUIRED_COLUMNS.issubset(
            reader.fieldnames
        ):
            raise RuntimeError(
                f"O ficheiro de dados iniciais {csv_path} não contém todas "
                "as colunas obrigatórias."
            )

        students: list[AlunoCSV] = []
        seen_ids: set[str] = set()
        invalid_rows: list[int] = []
        duplicate_rows: list[int] = []
        for line_number, row in enumerate(reader, start=2):
            try:
                student = AlunoCSV.model_validate(row)
            except ValidationError:
                invalid_rows.append(line_number)
                continue

            if student.id_aluno in seen_ids:
                duplicate_rows.append(line_number)
                continue
            seen_ids.add(student.id_aluno)
            students.append(student)
    return students, invalid_rows, duplicate_rows


def sync_seed_students(db: Session, csv_path: Path = SEED_FILE) -> None:
    students, invalid_rows, duplicate_rows = load_seed_students(csv_path)
    try:
        for student in students:
            email = str(student.email).strip().casefold()
            record_by_id = db.get(StudentModel, student.id_aluno)
            record_by_email = db.scalar(
                select(StudentModel).where(
                    StudentModel.email == email,
                )
            )
            if (
                record_by_id is not None
                and record_by_email is not None
                and record_by_id.student_id != record_by_email.student_id
            ):
                raise RuntimeError(
                    "O ID e o email de um estudante da massa inicial estão "
                    "associados a registos diferentes."
                )

            record = record_by_id or record_by_email
            if record is None:
                record = StudentModel(
                    student_id=student.id_aluno,
                    name=student.nome,
                    email=email,
                    math_grade=student.nota_matematica,
                    history_grade=student.nota_historia,
                    review_requested=False,
                )
                db.add(record)
            else:
                if record.student_id != student.id_aluno:
                    logger.info(
                        "Mantendo o UUID existente do aluno para sincronizar "
                        "a massa inicial (linha=%s).",
                        student.id_aluno,
                    )
                record.name = student.nome
                record.email = email
                record.math_grade = student.nota_matematica
                record.history_grade = student.nota_historia
        db.commit()
    except Exception:
        db.rollback()
        raise

    if invalid_rows or duplicate_rows:
        log_event(
            logger,
            "seed.rows_skipped",
            logging.WARNING,
            invalid_rows=invalid_rows,
            duplicate_rows=duplicate_rows,
        )
