import logging
from collections.abc import Sequence

from app.domain.exceptions import StudentAlreadyExistsError, StudentNotFoundError
from app.interfaces.interfaces import (
    ISyncNotifier,
    IStudentReadRepository,
    IStudentWriteRepository,
)
from app.models import StudentModel
from app.observability import log_event
from app.schemas.students import StudentCreate, StudentUpdate
from app.services.notifications import mask_email

logger = logging.getLogger(__name__)
_GRADE_FIELDS = {"math_grade": "Matemática", "history_grade": "História"}


def _grade(value: float) -> str:
    return f"{value:g}"


def grade_update_message(
    student: StudentModel, update_data: StudentUpdate
) -> tuple[str, str] | None:
    """Título e texto para o aluno; None se nenhuma nota mudou de valor."""
    changes = [
        (subject, getattr(student, field), getattr(update_data, field))
        for field, subject in _GRADE_FIELDS.items()
        if field in update_data.model_fields_set
        and getattr(update_data, field) != getattr(student, field)
    ]
    if not changes:
        return None
    lines = [
        f"{subject}: {_grade(before)} → {_grade(after)}/20"
        for subject, before, after in changes
    ]
    if len(changes) == 1:
        subject, before, after = changes[0]
        title = f"Nota de {subject} atualizada: {_grade(before)} → {_grade(after)}"
    else:
        title = "As suas notas foram atualizadas"
    body = "O professor atualizou as suas notas.\n\n" + "\n".join(lines)
    return title, body


class StudentAppService:
    def __init__(
        self,
        read_repo: IStudentReadRepository,
        write_repo: IStudentWriteRepository,
        notifier: ISyncNotifier,
    ) -> None:
        self.read_repo = read_repo
        self.write_repo = write_repo
        self.notifier = notifier

    def get_student(self, student_id: str) -> StudentModel:
        student = self.read_repo.get_by_id(student_id)
        if student is None:
            raise StudentNotFoundError(student_id)
        return student

    def get_students_page(
        self, page_number: int, page_size: int
    ) -> tuple[Sequence[StudentModel], int]:
        return self.read_repo.get_page(page_number, page_size)

    def get_students_under_review(self) -> Sequence[StudentModel]:
        return self.read_repo.get_under_review()

    def register_student(self, student_data: StudentCreate) -> StudentModel:
        if self.read_repo.get_by_email(str(student_data.email)) is not None:
            raise StudentAlreadyExistsError(
                "Email is already registered.",
                field="email",
            )
        new_student = self.write_repo.create(student_data)
        self.notifier.send_notification(
            new_student.email, "Bem-vindo à plataforma!"
        )
        return new_student

    def update_student(
        self, student_id: str, update_data: StudentUpdate
    ) -> StudentModel:
        existing_student = self.get_student(student_id)
        review_was_requested = existing_student.review_requested
        # Calculada antes de gravar: o modelo é o mesmo objeto da sessão.
        message = grade_update_message(existing_student, update_data)
        notification_id: int | None = None
        if message is None:
            updated_student = self.write_repo.update(student_id, update_data)
        else:
            result = self.write_repo.update_with_notification(
                student_id, update_data, message
            )
            updated_student, notification_id = result or (None, None)
        if updated_student is None:
            raise StudentNotFoundError(student_id)
        if message is not None and notification_id is not None:
            self._email_grade_update(updated_student.email, notification_id, message)
        if (
            update_data.review_requested is True
            and not review_was_requested
        ):
            self.notifier.send_notification(
                updated_student.email,
                "A sua solicitação de revisão foi iniciada.",
            )
        return updated_student

    def _email_grade_update(
        self, email: str, notification_id: int, message: tuple[str, str]
    ) -> None:
        """Email best-effort: a nota e a notificação in-app já estão gravadas."""
        title, body = message
        try:
            self.notifier.send_notification(email, f"{title}\n\n{body}")
        except Exception as error:
            log_event(
                logger,
                "student.grade_notification_failed",
                logging.WARNING,
                recipient=mask_email(email),
                error_type=type(error).__name__,
            )
            self.write_repo.set_notification_email_status(notification_id, "failed")
            return
        self.write_repo.set_notification_email_status(notification_id, "sent")

    def delete_student(self, student_id: str) -> None:
        if not self.write_repo.delete(student_id):
            raise StudentNotFoundError(student_id)
