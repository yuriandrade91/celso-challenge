from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.review_exceptions import ReviewRequestConflictError
from app.models import ReviewRequestModel, StudentModel, StudentNotificationModel
from app.schemas.reviews import ReviewDecision, ReviewRequestCreate


class ReviewRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_for_student(
        self, student_id: str
    ) -> Sequence[tuple[ReviewRequestModel, StudentModel]]:
        statement = (
            select(ReviewRequestModel, StudentModel)
            .join(StudentModel, StudentModel.student_id == ReviewRequestModel.student_id)
            .where(ReviewRequestModel.student_id == student_id)
            .order_by(ReviewRequestModel.created_at.desc(), ReviewRequestModel.id.desc())
        )
        return self.db.execute(statement).all()

    def get_pending(self) -> Sequence[tuple[ReviewRequestModel, StudentModel]]:
        statement = (
            select(ReviewRequestModel, StudentModel)
            .join(StudentModel, StudentModel.student_id == ReviewRequestModel.student_id)
            .where(ReviewRequestModel.status == "pending")
            .order_by(ReviewRequestModel.created_at, ReviewRequestModel.id)
        )
        return self.db.execute(statement).all()

    def create(
        self, student: StudentModel, request: ReviewRequestCreate
    ) -> tuple[ReviewRequestModel, StudentModel]:
        grade_field = f"{request.subject}_grade"
        review = ReviewRequestModel(
            student_id=student.student_id,
            subject=request.subject,
            justification=request.justification,
            original_grade=getattr(student, grade_field),
        )
        student.review_requested = True
        self.db.add(review)
        try:
            self.db.commit()
        except IntegrityError as error:
            self.db.rollback()
            raise ReviewRequestConflictError(
                "Já existe um pedido pendente para esta disciplina."
            ) from error
        self.db.refresh(review)
        return review, student

    def decide(
        self,
        review: ReviewRequestModel,
        student: StudentModel,
        decision: ReviewDecision,
        notification: tuple[str, str] | None = None,
    ) -> tuple[ReviewRequestModel, StudentModel]:
        """Aplica a decisão; `notification` (título, texto) entra no mesmo commit."""
        review.status = decision.action
        review.teacher_response = decision.teacher_response
        review.adjusted_grade = decision.adjusted_grade
        review.decided_at = datetime.now(UTC)
        student.review_requested = bool(
            self.db.scalar(
                select(
                    exists().where(
                        ReviewRequestModel.student_id == student.student_id,
                        ReviewRequestModel.status == "pending",
                        ReviewRequestModel.id != review.id,
                    )
                )
            )
        )
        if decision.action == "adjusted":
            if decision.adjusted_grade is None:
                raise ValueError("A nova nota é obrigatória para aplicar um ajuste.")
            setattr(student, f"{review.subject}_grade", decision.adjusted_grade)
        if notification is not None:
            title, body = notification
            self.db.add(
                StudentNotificationModel(
                    student_id=student.student_id,
                    kind="review_decision",
                    review_id=review.id,
                    title=title,
                    summary=body,
                    math_grade=student.math_grade,
                    history_grade=student.history_grade,
                    email_status="pending",
                )
            )
        self.db.commit()
        self.db.refresh(review)
        self.db.refresh(student)
        return review, student

    def get_by_id(self, review_id: int) -> ReviewRequestModel | None:
        return self.db.get(ReviewRequestModel, review_id)

    def delete(self, review: ReviewRequestModel) -> None:
        student = self.get_student(review.student_id)
        if student is not None:
            student.review_requested = bool(
                self.db.scalar(
                    select(
                        exists().where(
                            ReviewRequestModel.student_id == student.student_id,
                            ReviewRequestModel.status == "pending",
                            ReviewRequestModel.id != review.id,
                        )
                    )
                )
            )
        self.db.delete(review)
        self.db.commit()

    def get_student(self, student_id: str) -> StudentModel | None:
        return self.db.get(StudentModel, student_id)

    def get_review_notification(
        self, review_id: int
    ) -> StudentNotificationModel | None:
        return self.db.scalar(
            select(StudentNotificationModel).where(
                StudentNotificationModel.review_id == review_id,
                StudentNotificationModel.kind == "review_decision",
            )
        )

    def set_notification_email_status(
        self, notification: StudentNotificationModel, status: str
    ) -> None:
        notification.email_status = status
        self.db.commit()
