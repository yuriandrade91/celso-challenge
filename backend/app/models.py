from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class UserModel(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "role IN ('student', 'teacher')",
            name="ck_users_role",
        ),
        CheckConstraint(
            "(role = 'teacher' AND student_id IS NULL) OR "
            "(role = 'student' AND student_id IS NOT NULL)",
            name="ck_users_role_student_link",
        ),
    )

    email: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)
    student_id: Mapped[str | None] = mapped_column(
        String, unique=True, nullable=True, index=True
    )


class RefreshTokenModel(Base):
    __tablename__ = "refresh_tokens"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_email: Mapped[str] = mapped_column(String, nullable=False, index=True)
    expires_at: Mapped[int] = mapped_column(Integer, nullable=False)
    revoked_at: Mapped[int | None] = mapped_column(Integer, nullable=True)


class StudentModel(Base):
    __tablename__ = "students"

    student_id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    math_grade: Mapped[float] = mapped_column(Float, nullable=False)
    history_grade: Mapped[float] = mapped_column(Float, nullable=False)
    review_requested: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )


class ReviewRequestModel(Base):
    __tablename__ = "review_requests"
    __table_args__ = (
        CheckConstraint(
            "subject IN ('math', 'history')",
            name="ck_review_requests_subject",
        ),
        CheckConstraint(
            "status IN ('pending', 'adjusted', 'cancelled')",
            name="ck_review_requests_status",
        ),
        Index(
            "uq_review_requests_pending_student_subject",
            "student_id",
            "subject",
            unique=True,
            sqlite_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    student_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    subject: Mapped[str] = mapped_column(String, nullable=False)
    justification: Mapped[str] = mapped_column(Text, nullable=False)
    original_grade: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    teacher_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    adjusted_grade: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class GradeReportModel(Base):
    __tablename__ = "boletins"

    id_aluno: Mapped[str] = mapped_column(String, primary_key=True)
    nome: Mapped[str | None] = mapped_column(String, nullable=True)
    hash_notas: Mapped[str | None] = mapped_column(String, nullable=True)
    resumo_llm: Mapped[str | None] = mapped_column(String, nullable=True)
    status_revisao: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    email: Mapped[str | None] = mapped_column(String, nullable=True)
    nota_matematica: Mapped[float | None] = mapped_column(Float, nullable=True)
    nota_historia: Mapped[float | None] = mapped_column(Float, nullable=True)
    tokens_gastos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status_notificacao: Mapped[str] = mapped_column(
        String, nullable=False, default="pending"
    )
    # Reserva (lease) para que execuções concorrentes não processem o mesmo aluno.
    processing_owner: Mapped[str | None] = mapped_column(String(32), nullable=True)
    processing_until: Mapped[int | None] = mapped_column(Integer, nullable=True)


class GradeReportExecutionModel(Base):
    __tablename__ = "grade_report_executions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    execution_id: Mapped[str | None] = mapped_column(
        String(32), nullable=True, unique=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    total_linhas: Mapped[int] = mapped_column(Integer, nullable=False)
    processados: Mapped[int] = mapped_column(Integer, nullable=False)
    falhas: Mapped[int] = mapped_column(Integer, nullable=False)
    tokens_gastos: Mapped[int] = mapped_column(Integer, nullable=False)
    custo_estimado_usd: Mapped[float] = mapped_column(Float, nullable=False)
    tempo_total_ms: Mapped[float] = mapped_column(Float, nullable=False)
    tempo_medio_processamento_ms: Mapped[float] = mapped_column(
        Float, nullable=False
    )
    tempo_p95_processamento_ms: Mapped[float] = mapped_column(
        Float, nullable=False, default=0
    )
    ignorados_cache: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicados_ignorados: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    falhas_validacao: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    falhas_processamento: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    fallbacks_llm: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    em_processamento: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    orcamento_excedido: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="completed")
    erro: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_provider: Mapped[str] = mapped_column(String, nullable=False)
    notification_provider: Mapped[str] = mapped_column(String, nullable=False)


class AcademicTermModel(Base):
    """Semestre/período letivo; o fecho gera o boletim de cada aluno."""

    __tablename__ = "academic_terms"
    __table_args__ = (
        CheckConstraint(
            "status IN ('open', 'closing', 'closed')",
            name="ck_academic_terms_status",
        ),
        CheckConstraint("end_date >= start_date", name="ck_academic_terms_dates"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    # Lease do fecho: impede dois fechos simultâneos e expira se o processo cair.
    closing_owner: Mapped[str | None] = mapped_column(String(32), nullable=True)
    closing_until: Mapped[int | None] = mapped_column(Integer, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    closed_by: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class StudentNotificationModel(Base):
    """Central de notificações do aluno (boletim, decisão de revisão, nota editada).

    A unicidade (aluno, semestre, tipo) torna o fecho de semestre idempotente;
    no SQLite, term_id NULL não colide, por isso as revisões não são afetadas.
    """

    __tablename__ = "student_notifications"
    __table_args__ = (
        UniqueConstraint(
            "student_id", "term_id", "kind", name="uq_student_notifications_term"
        ),
        CheckConstraint(
            "kind IN ('term_report', 'review_decision', 'grade_update')",
            name="ck_student_notifications_kind",
        ),
        CheckConstraint(
            "email_status IN ('pending', 'sent', 'failed')",
            name="ck_student_notifications_email_status",
        ),
        CheckConstraint(
            "summary_source IS NULL OR summary_source IN ('llm', 'template', 'cache')",
            name="ck_student_notifications_summary_source",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    student_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="term_report")
    term_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    review_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    math_grade: Mapped[float] = mapped_column(Float, nullable=False)
    history_grade: Mapped[float] = mapped_column(Float, nullable=False)
    summary_source: Mapped[str | None] = mapped_column(String(16), nullable=True)
    tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    email_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending"
    )
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
