from collections.abc import Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.security import get_auth_settings, hash_password
from app.domain.exceptions import StudentAlreadyExistsError
from app.interfaces.interfaces import IStudentReadRepository, IStudentWriteRepository
from app.models import (
    RefreshTokenModel,
    ReviewRequestModel,
    StudentModel,
    StudentNotificationModel,
    UserModel,
)
from app.schemas.students import StudentCreate, StudentUpdate


class SQLiteStudentRepository(IStudentReadRepository, IStudentWriteRepository):
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_id(self, student_id: str) -> StudentModel | None:
        return self.db.get(StudentModel, student_id)

    def get_by_email(self, email: str) -> StudentModel | None:
        statement = select(StudentModel).where(StudentModel.email == email)
        return self.db.scalar(statement)

    def get_page(
        self, page_number: int, page_size: int
    ) -> tuple[Sequence[StudentModel], int]:
        total_records = self.db.scalar(select(func.count()).select_from(StudentModel))
        statement = (
            select(StudentModel)
            .order_by(StudentModel.student_id)
            .offset((page_number - 1) * page_size)
            .limit(page_size)
        )
        return self.db.scalars(statement).all(), total_records or 0

    def get_under_review(self) -> Sequence[StudentModel]:
        statement = (
            select(StudentModel)
            .where(StudentModel.review_requested.is_(True))
            .order_by(StudentModel.student_id)
        )
        return self.db.scalars(statement).all()

    def create(self, student: StudentCreate) -> StudentModel:
        email = str(student.email).strip().casefold()
        if self.db.get(UserModel, email) is not None:
            raise StudentAlreadyExistsError(
                "Email is already registered.",
                field="email",
            )
        if self.db.get(StudentModel, student.student_id) is not None:
            raise StudentAlreadyExistsError(
                "Student ID is already registered.",
                field="studentId",
            )
        db_student = StudentModel(
            **student.model_dump(exclude={"email"}),
            email=email,
        )
        settings = get_auth_settings()
        student_account = UserModel(
            email=email,
            password_hash=hash_password(settings.student_password),
            role="student",
            student_id=db_student.student_id,
        )
        self.db.add(db_student)
        self.db.add(student_account)
        try:
            self.db.commit()
        except IntegrityError as error:
            self.db.rollback()
            raise StudentAlreadyExistsError(
                "Student ID or email is already registered."
            ) from error
        self.db.refresh(db_student)
        return db_student

    def update(
        self, student_id: str, update_data: StudentUpdate
    ) -> StudentModel | None:
        db_student = self.get_by_id(student_id)
        if db_student is None:
            return None

        self._apply_update(db_student, update_data)
        self.db.commit()
        self.db.refresh(db_student)
        return db_student

    def update_with_notification(
        self,
        student_id: str,
        update_data: StudentUpdate,
        notification: tuple[str, str],
    ) -> tuple[StudentModel, int] | None:
        db_student = self.get_by_id(student_id)
        if db_student is None:
            return None

        self._apply_update(db_student, update_data)
        title, body = notification
        # Fotografia das notas já atualizadas, para o aluno ver o novo valor.
        record = StudentNotificationModel(
            student_id=student_id,
            kind="grade_update",
            title=title,
            summary=body,
            math_grade=db_student.math_grade,
            history_grade=db_student.history_grade,
            email_status="pending",
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(db_student)
        return db_student, record.id

    def set_notification_email_status(self, notification_id: int, status: str) -> None:
        record = self.db.get(StudentNotificationModel, notification_id)
        if record is not None:
            record.email_status = status
            self.db.commit()

    @staticmethod
    def _apply_update(db_student: StudentModel, update_data: StudentUpdate) -> None:
        for key, value in update_data.model_dump(exclude_unset=True).items():
            if value is not None:
                setattr(db_student, key, value)

    def delete(self, student_id: str) -> bool:
        db_student = self.get_by_id(student_id)
        if db_student is None:
            return False
        email = db_student.email.strip().casefold()
        account = self.db.get(UserModel, email)
        if account is not None and account.student_id == student_id:
            self.db.execute(
                delete(RefreshTokenModel).where(
                    RefreshTokenModel.user_email == email
                )
            )
            self.db.delete(account)
        self.db.execute(
            delete(ReviewRequestModel).where(
                ReviewRequestModel.student_id == student_id
            )
        )
        self.db.execute(
            delete(StudentNotificationModel).where(
                StudentNotificationModel.student_id == student_id
            )
        )
        self.db.delete(db_student)
        self.db.commit()
        return True
