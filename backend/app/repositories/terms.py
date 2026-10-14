import time
from datetime import datetime, timezone

from sqlalchemy import case, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.term_exceptions import TermConflictError
from app.interfaces.interfaces import (
    ITermClosingRepository,
    RosterStudent,
    StoredNotification,
    TermSnapshot,
)
from app.models import (
    AcademicTermModel,
    GradeReportModel,
    StudentModel,
    StudentNotificationModel,
)
from app.schemas.terms import (
    StudentInbox,
    StudentNotificationResponse,
    TermCreate,
    TermDelivery,
    TermDeliveryStats,
    TermResponse,
    TermUpdate,
)

TERM_REPORT = "term_report"


class TermRepository(ITermClosingRepository):
    def __init__(self, db: Session) -> None:
        self.db = db

    # --- Gestão de semestres -------------------------------------------------

    def _delivery_stats(self, term_ids: list[int]) -> dict[int, TermDeliveryStats]:
        if not term_ids:
            return {}
        table = StudentNotificationModel
        rows = self.db.execute(
            select(
                table.term_id,
                func.count(),
                func.sum(case((table.email_status != "sent", 1), else_=0)),
                func.sum(case((table.read_at.is_not(None), 1), else_=0)),
            )
            .where(table.term_id.in_(term_ids))
            .group_by(table.term_id)
        ).all()
        return {
            term_id: TermDeliveryStats(
                alunos_notificados=total,
                emails_pendentes=pending or 0,
                notificacoes_lidas=read or 0,
            )
            for term_id, total, pending, read in rows
        }

    def _to_response(
        self, term: AcademicTermModel, stats: TermDeliveryStats | None
    ) -> TermResponse:
        return TermResponse(
            id=term.id,
            code=term.code,
            name=term.name,
            start_date=term.start_date,
            end_date=term.end_date,
            status=term.status,
            closed_at=term.closed_at,
            closed_by=term.closed_by,
            created_at=term.created_at,
            entregas=stats or TermDeliveryStats(),
        )

    def list_terms(self) -> list[TermResponse]:
        terms = self.db.scalars(
            select(AcademicTermModel).order_by(
                AcademicTermModel.end_date.desc(), AcademicTermModel.id.desc()
            )
        ).all()
        stats = self._delivery_stats([term.id for term in terms])
        return [self._to_response(term, stats.get(term.id)) for term in terms]

    def get_term(self, term_id: int) -> TermResponse | None:
        term = self.db.get(AcademicTermModel, term_id)
        if term is None:
            return None
        return self._to_response(term, self._delivery_stats([term_id]).get(term_id))

    def create_term(self, data: TermCreate) -> TermResponse:
        term = AcademicTermModel(
            code=data.code.strip(),
            name=data.name.strip(),
            start_date=data.start_date,
            end_date=data.end_date,
            status="open",
        )
        self.db.add(term)
        try:
            self.db.commit()
        except IntegrityError as error:
            self.db.rollback()
            raise TermConflictError("Já existe um semestre com este código.") from error
        self.db.refresh(term)
        return self._to_response(term, None)

    def update_term(self, term_id: int, data: TermUpdate) -> TermResponse | None:
        term = self.db.get(AcademicTermModel, term_id)
        if term is None:
            return None
        if term.status != "open":
            raise TermConflictError("Só é possível editar semestres abertos.")
        changes = data.model_dump(exclude_unset=True)
        start = changes.get("start_date", term.start_date)
        end = changes.get("end_date", term.end_date)
        if end < start:
            raise TermConflictError(
                "A data de fecho deve ser igual ou posterior ao início."
            )
        for key, value in changes.items():
            setattr(term, key, value.strip() if isinstance(value, str) else value)
        self.db.commit()
        self.db.refresh(term)
        return self._to_response(term, self._delivery_stats([term_id]).get(term_id))

    def delete_term(self, term_id: int) -> bool:
        term = self.db.get(AcademicTermModel, term_id)
        if term is None:
            return False
        has_notifications = self.db.scalar(
            select(func.count())
            .select_from(StudentNotificationModel)
            .where(StudentNotificationModel.term_id == term_id)
        )
        if term.status != "open" or has_notifications:
            raise TermConflictError(
                "Semestres fechados ou com notificações enviadas não podem ser excluídos."
            )
        self.db.delete(term)
        self.db.commit()
        return True

    def deliveries(self, term_id: int) -> list[TermDelivery]:
        rows = self.db.execute(
            select(StudentNotificationModel, StudentModel)
            .outerjoin(
                StudentModel,
                StudentModel.student_id == StudentNotificationModel.student_id,
            )
            .where(StudentNotificationModel.term_id == term_id)
            .order_by(StudentModel.name, StudentNotificationModel.id)
        ).all()
        return [
            TermDelivery(
                notification_id=notification.id,
                student_id=notification.student_id,
                student_name=student.name if student else "Aluno removido",
                student_email=student.email if student else "",
                math_grade=notification.math_grade,
                history_grade=notification.history_grade,
                summary_source=notification.summary_source or "template",
                email_status=notification.email_status,
                read_at=notification.read_at,
                created_at=notification.created_at,
            )
            for notification, student in rows
        ]

    # --- Caixa de entrada do aluno -------------------------------------------

    def inbox(self, student_id: str, limit: int) -> StudentInbox:
        rows = self.db.execute(
            select(StudentNotificationModel, AcademicTermModel)
            .outerjoin(
                AcademicTermModel,
                AcademicTermModel.id == StudentNotificationModel.term_id,
            )
            .where(StudentNotificationModel.student_id == student_id)
            .order_by(StudentNotificationModel.id.desc())
            .limit(limit)
        ).all()
        unread = self.db.scalar(
            select(func.count())
            .select_from(StudentNotificationModel)
            .where(
                StudentNotificationModel.student_id == student_id,
                StudentNotificationModel.read_at.is_(None),
            )
        )
        return StudentInbox(
            unread_count=unread or 0,
            items=[
                StudentNotificationResponse(
                    id=notification.id,
                    kind=notification.kind,
                    term_id=notification.term_id,
                    term_code=term.code if term else None,
                    term_name=term.name if term else None,
                    review_id=notification.review_id,
                    title=notification.title,
                    summary=notification.summary,
                    math_grade=notification.math_grade,
                    history_grade=notification.history_grade,
                    read_at=notification.read_at,
                    created_at=notification.created_at,
                )
                for notification, term in rows
            ],
        )

    def mark_read(self, notification_id: int, student_id: str) -> bool:
        """Marca como lida; False se a notificação não pertence ao aluno."""
        notification = self.db.get(StudentNotificationModel, notification_id)
        if notification is None or notification.student_id != student_id:
            return False
        if notification.read_at is None:
            notification.read_at = datetime.now(timezone.utc)
            self.db.commit()
        return True

    def mark_all_read(self, student_id: str) -> int:
        result = self.db.execute(
            update(StudentNotificationModel)
            .where(
                StudentNotificationModel.student_id == student_id,
                StudentNotificationModel.read_at.is_(None),
            )
            .values(read_at=datetime.now(timezone.utc))
            .execution_options(synchronize_session=False)
        )
        self.db.commit()
        self.db.expire_all()
        return result.rowcount

    # --- Pipeline de fecho (ITermClosingRepository) --------------------------

    def get_term_snapshot(self, term_id: int) -> TermSnapshot | None:
        term = self.db.get(AcademicTermModel, term_id)
        if term is None:
            return None
        return TermSnapshot(
            id=term.id, code=term.code, name=term.name, status=term.status
        )

    def claim_closing(self, term_id: int, owner: str, lease_seconds: int) -> bool:
        now = int(time.time())
        # UPDATE condicional e atómico: um único fecho ativo por semestre.
        result = self.db.execute(
            update(AcademicTermModel)
            .where(
                AcademicTermModel.id == term_id,
                or_(
                    AcademicTermModel.status.in_(("open", "closed")),
                    AcademicTermModel.closing_until < now,
                ),
            )
            .values(
                status="closing",
                closing_owner=owner,
                closing_until=now + lease_seconds,
            )
            .execution_options(synchronize_session=False)
        )
        self.db.commit()
        self.db.expire_all()
        return result.rowcount == 1

    def finish_closing(self, term_id: int, owner: str, closed_by: str) -> None:
        term = self.db.get(AcademicTermModel, term_id)
        if term is None or term.closing_owner != owner:
            return
        term.status = "closed"
        term.closing_owner = None
        term.closing_until = None
        # Reenvios não reescrevem quem fechou nem quando.
        if term.closed_at is None:
            term.closed_at = datetime.now(timezone.utc)
            term.closed_by = closed_by
        self.db.commit()

    def abort_closing(self, term_id: int, owner: str) -> None:
        term = self.db.get(AcademicTermModel, term_id)
        if term is None or term.closing_owner != owner:
            return
        term.status = "closed" if term.closed_at else "open"
        term.closing_owner = None
        term.closing_until = None
        self.db.commit()

    def roster(self) -> list[RosterStudent]:
        students = self.db.scalars(
            select(StudentModel).order_by(StudentModel.name)
        ).all()
        return [
            RosterStudent(
                student_id=student.student_id,
                name=student.name,
                email=student.email,
                math_grade=student.math_grade,
                history_grade=student.history_grade,
            )
            for student in students
        ]

    def get_notification(
        self, student_id: str, term_id: int
    ) -> StoredNotification | None:
        notification = self.db.scalar(
            select(StudentNotificationModel).where(
                StudentNotificationModel.student_id == student_id,
                StudentNotificationModel.term_id == term_id,
                StudentNotificationModel.kind == TERM_REPORT,
            )
        )
        if notification is None:
            return None
        return StoredNotification(
            id=notification.id,
            summary=notification.summary,
            email_status=notification.email_status,
        )

    def cached_summary(self, student_id: str, report_hash: str) -> str | None:
        report = self.db.get(GradeReportModel, student_id)
        if report is None or report.hash_notas != report_hash:
            return None
        return report.resumo_llm or None

    def save_notification(
        self,
        term_id: int,
        student: RosterStudent,
        title: str,
        summary: str,
        summary_source: str,
        tokens: int,
    ) -> int:
        notification = StudentNotificationModel(
            student_id=student.student_id,
            term_id=term_id,
            kind=TERM_REPORT,
            title=title,
            summary=summary,
            math_grade=student.math_grade,
            history_grade=student.history_grade,
            summary_source=summary_source,
            tokens=tokens,
            email_status="pending",
        )
        self.db.add(notification)
        self.db.commit()
        return notification.id

    def set_email_status(self, notification_id: int, status: str) -> None:
        notification = self.db.get(StudentNotificationModel, notification_id)
        if notification is None:
            raise LookupError("Notificação não encontrada para atualizar o envio.")
        notification.email_status = status
        self.db.commit()
