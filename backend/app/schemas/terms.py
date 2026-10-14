from datetime import date
from typing import Literal

from pydantic import Field, model_validator

from app.schemas.reports import RowValidationError
from app.schemas.responses import ApiModel, UtcDateTime

TermStatus = Literal["open", "closing", "closed"]
EmailStatus = Literal["pending", "sent", "failed"]
SummarySource = Literal["llm", "template", "cache"]


class TermCreate(ApiModel):
    code: str = Field(min_length=1, max_length=20, pattern=r"^[A-Za-z0-9._/-]+$")
    name: str = Field(min_length=1, max_length=120)
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def end_after_start(self) -> "TermCreate":
        if self.end_date < self.start_date:
            raise ValueError("A data de fecho deve ser igual ou posterior ao início.")
        return self


class TermUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def reject_explicit_nulls(self) -> "TermUpdate":
        if any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("Campos enviados para atualização não podem ser nulos.")
        return self


class TermDeliveryStats(ApiModel):
    alunos_notificados: int = 0
    emails_pendentes: int = 0
    notificacoes_lidas: int = 0


class TermResponse(ApiModel):
    id: int
    code: str
    name: str
    start_date: date
    end_date: date
    status: TermStatus
    closed_at: UtcDateTime | None
    closed_by: str | None
    created_at: UtcDateTime
    entregas: TermDeliveryStats


class TermCloseReport(ApiModel):
    term_id: int
    execution_id: str
    total_alunos: int = 0
    notificados: int = 0
    ja_notificados: int = 0
    resumos_reaproveitados: int = 0
    falhas: int = 0
    fallbacks_llm: int = 0
    orcamento_excedido: bool = False
    tokens_gastos: int = 0
    custo_estimado_usd: float = 0
    tempo_total_ms: float = 0
    summary_provider: str = "mock"
    notification_provider: str = "mock"
    erros: list[RowValidationError] = Field(default_factory=list)


class TermDelivery(ApiModel):
    """Visão do professor: o que cada aluno recebeu no fecho."""

    notification_id: int
    student_id: str
    student_name: str
    student_email: str
    math_grade: float
    history_grade: float
    summary_source: SummarySource
    email_status: EmailStatus
    read_at: UtcDateTime | None
    created_at: UtcDateTime


NotificationKind = Literal["term_report", "review_decision", "grade_update"]


class StudentNotificationResponse(ApiModel):
    id: int
    kind: NotificationKind
    term_id: int | None
    term_code: str | None
    term_name: str | None
    review_id: int | None
    title: str
    summary: str
    math_grade: float
    history_grade: float
    read_at: UtcDateTime | None
    created_at: UtcDateTime


class StudentInbox(ApiModel):
    unread_count: int
    items: list[StudentNotificationResponse]
