from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass

from app.models import StudentModel
from app.schemas.reports import AlunoCSV
from app.schemas.students import StudentCreate, StudentUpdate


@dataclass(frozen=True)
class StoredGradeReport:
    grades_hash: str | None
    summary: str | None
    tokens: int
    notification_status: str


class IGradeReportRepository(ABC):
    """Boletins gerados, estado de envio e reserva por aluno."""

    @abstractmethod
    def get_report(self, student_id: str) -> StoredGradeReport | None:
        raise NotImplementedError

    @abstractmethod
    def save_report(
        self, student: AlunoCSV, grades_hash: str, summary: str, tokens: int
    ) -> bool:
        raise NotImplementedError

    @abstractmethod
    def mark_report_notified(self, student_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def upsert_student(self, student: AlunoCSV) -> None:
        """Alinha o cadastro com a linha do CSV ou lança RosterConflictError."""
        raise NotImplementedError

    @abstractmethod
    def claim_report(self, student_id: str, owner: str, lease_seconds: int) -> bool:
        """Reserva o aluno para uma execução; False se outra o processa."""
        raise NotImplementedError

    @abstractmethod
    def release_report(self, student_id: str, owner: str) -> None:
        raise NotImplementedError


class ISummarizer(ABC):
    @property
    @abstractmethod
    def provider_name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    async def generate(self, student: AlunoCSV) -> "SummaryResult":
        raise NotImplementedError

    def estimate_max_cost(self, student: AlunoCSV) -> float:
        """Custo máximo de uma chamada, usado para reservar orçamento."""
        return 0.0


@dataclass(frozen=True)
class SummaryResult:
    summary: str
    prompt_tokens: int
    completion_tokens: int
    estimated_cost_usd: float
    used_fallback: bool = False


class IStudentReadRepository(ABC):
    @abstractmethod
    def get_by_id(self, student_id: str) -> StudentModel | None:
        raise NotImplementedError

    @abstractmethod
    def get_by_email(self, email: str) -> StudentModel | None:
        raise NotImplementedError

    @abstractmethod
    def get_page(
        self, page_number: int, page_size: int
    ) -> tuple[Sequence[StudentModel], int]:
        raise NotImplementedError

    @abstractmethod
    def get_under_review(self) -> Sequence[StudentModel]:
        raise NotImplementedError


class IStudentWriteRepository(ABC):
    @abstractmethod
    def create(self, student: StudentCreate) -> StudentModel:
        raise NotImplementedError

    @abstractmethod
    def update(
        self, student_id: str, update_data: StudentUpdate
    ) -> StudentModel | None:
        raise NotImplementedError

    @abstractmethod
    def update_with_notification(
        self,
        student_id: str,
        update_data: StudentUpdate,
        notification: tuple[str, str],
    ) -> tuple[StudentModel, int] | None:
        """Atualiza e grava a notificação (título, texto) no mesmo commit."""
        raise NotImplementedError

    @abstractmethod
    def set_notification_email_status(self, notification_id: int, status: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def delete(self, student_id: str) -> bool:
        raise NotImplementedError


class ISyncNotifier(ABC):
    @abstractmethod
    def send_notification(self, recipient: str, message: str) -> None:
        raise NotImplementedError


class INotifier(ABC):
    @property
    def provider_name(self) -> str:
        return type(self).__name__

    @abstractmethod
    async def send_notification(self, recipient: str, message: str) -> None:
        raise NotImplementedError


@dataclass(frozen=True)
class TermSnapshot:
    id: int
    code: str
    name: str
    status: str


@dataclass(frozen=True)
class RosterStudent:
    student_id: str
    name: str
    email: str
    math_grade: float
    history_grade: float


@dataclass(frozen=True)
class StoredNotification:
    id: int
    summary: str
    email_status: str


class ITermClosingRepository(ABC):
    """O que o fecho de semestre precisa do armazenamento."""

    @abstractmethod
    def get_term_snapshot(self, term_id: int) -> TermSnapshot | None:
        raise NotImplementedError

    @abstractmethod
    def claim_closing(self, term_id: int, owner: str, lease_seconds: int) -> bool:
        """Passa o semestre a `closing`; False se outro fecho está ativo."""
        raise NotImplementedError

    @abstractmethod
    def finish_closing(self, term_id: int, owner: str, closed_by: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def abort_closing(self, term_id: int, owner: str) -> None:
        """Devolve o semestre ao estado anterior ao fecho interrompido."""
        raise NotImplementedError

    @abstractmethod
    def roster(self) -> list[RosterStudent]:
        raise NotImplementedError

    @abstractmethod
    def get_notification(
        self, student_id: str, term_id: int
    ) -> StoredNotification | None:
        raise NotImplementedError

    @abstractmethod
    def cached_summary(self, student_id: str, report_hash: str) -> str | None:
        """Resumo já gerado para as mesmas notas (boletins), para poupar tokens."""
        raise NotImplementedError

    @abstractmethod
    def save_notification(
        self,
        term_id: int,
        student: RosterStudent,
        title: str,
        summary: str,
        summary_source: str,
        tokens: int,
    ) -> int:
        raise NotImplementedError

    @abstractmethod
    def set_email_status(self, notification_id: int, status: str) -> None:
        raise NotImplementedError
