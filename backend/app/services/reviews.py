import logging
from collections.abc import Sequence

from app.domain.exceptions import StudentNotFoundError
from app.domain.review_exceptions import (
    ReviewRequestConflictError,
    ReviewRequestNotFoundError,
)
from app.interfaces.interfaces import ISyncNotifier
from app.models import ReviewRequestModel, StudentModel
from app.observability import log_event
from app.repositories.reviews import ReviewRepository
from app.schemas.reviews import ReviewDecision, ReviewRequestCreate
from app.services.notifications import mask_email

logger = logging.getLogger(__name__)
ReviewWithStudent = tuple[ReviewRequestModel, StudentModel]
_SUBJECT_NAMES = {"math": "Matemática", "history": "História"}


def _grade(value: float) -> str:
    return f"{value:g}"


def review_decision_message(
    review: ReviewRequestModel, decision: ReviewDecision
) -> tuple[str, str]:
    """Título e texto da notificação que o aluno recebe sobre a decisão."""
    subject = _SUBJECT_NAMES[review.subject]
    original = _grade(review.original_grade)
    if decision.action == "adjusted" and decision.adjusted_grade is not None:
        adjusted = _grade(decision.adjusted_grade)
        title = f"Nota de {subject} revista: {original} → {adjusted}"
        body = (
            f"O professor analisou o seu pedido de revisão de {subject} e "
            f"ajustou a nota de {original} para {adjusted}/20."
        )
    else:
        title = f"Pedido de revisão de {subject} encerrado"
        body = (
            f"O professor analisou o seu pedido de revisão de {subject} e "
            f"manteve a nota {original}/20."
        )
    return title, f"{body}\n\nResposta do professor: {decision.teacher_response}"


class ReviewService:
    def __init__(
        self, repository: ReviewRepository, notifier: ISyncNotifier | None = None
    ) -> None:
        self.repository = repository
        self.notifier = notifier

    def get_student_reviews(self, student_id: str) -> Sequence[ReviewWithStudent]:
        if self.repository.get_student(student_id) is None:
            raise StudentNotFoundError(student_id)
        return self.repository.get_for_student(student_id)

    def get_pending_reviews(self) -> Sequence[ReviewWithStudent]:
        return self.repository.get_pending()

    def request_review(
        self, student_id: str, request: ReviewRequestCreate
    ) -> ReviewWithStudent:
        student = self.repository.get_student(student_id)
        if student is None:
            raise StudentNotFoundError(student_id)
        if any(
            review.subject == request.subject and review.status == "pending"
            for review, _ in self.repository.get_for_student(student_id)
        ):
            raise ReviewRequestConflictError(
                "Já existe um pedido pendente para esta disciplina."
            )
        return self.repository.create(student, request)

    def decide_review(
        self, review_id: int, decision: ReviewDecision
    ) -> ReviewWithStudent:
        review = self.repository.get_by_id(review_id)
        if review is None:
            raise ReviewRequestNotFoundError(review_id)
        if review.status != "pending":
            raise ReviewRequestConflictError(
                "Este pedido já foi analisado e não pode ser alterado."
            )
        student = self.repository.get_student(review.student_id)
        if student is None:
            raise StudentNotFoundError(review.student_id)
        message = review_decision_message(review, decision)
        result = self.repository.decide(review, student, decision, message)
        self._email_decision(review.id, student.email, message)
        return result

    def _email_decision(
        self, review_id: int, email: str, message: tuple[str, str]
    ) -> None:
        """Email best-effort: a decisão e a notificação in-app já estão gravadas."""
        notification = self.repository.get_review_notification(review_id)
        if self.notifier is None or notification is None:
            return
        title, body = message
        try:
            self.notifier.send_notification(email, f"{title}\n\n{body}")
        except Exception as error:
            log_event(
                logger,
                "review.notification_failed",
                logging.WARNING,
                recipient=mask_email(email),
                error_type=type(error).__name__,
            )
            self.repository.set_notification_email_status(notification, "failed")
            return
        self.repository.set_notification_email_status(notification, "sent")

    def delete_pending_review(self, review_id: int) -> None:
        review = self.repository.get_by_id(review_id)
        if review is None:
            raise ReviewRequestNotFoundError(review_id)
        if review.status != "pending":
            raise ReviewRequestConflictError(
                "Apenas pedidos pendentes podem ser excluídos."
            )
        self.repository.delete(review)
