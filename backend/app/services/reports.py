import asyncio
import hashlib
import io
import logging
import math
import os
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, Literal, TypeVar

import pandas as pd
from pydantic import ValidationError

from app.domain.exceptions import ConfigurationError, RosterConflictError
from app.interfaces.interfaces import (
    IGradeReportRepository,
    INotifier,
    ISummarizer,
    SummaryResult,
)
from app.metrics import percentile
from app.observability import execution_id_var, log_event, span
from app.schemas.reports import AlunoCSV, RowValidationError, UploadReport
from app.services.notifications import mask_email
from app.services.providers import (
    MockSummarizer,
    ProviderRequestError,
    TemplateSummarizer,
)

logger = logging.getLogger(__name__)
_SAFE_ERRORS = (ProviderRequestError, RosterConflictError)
T = TypeVar("T")


def hash_grades(math_grade: float, history_grade: float) -> str:
    return hashlib.sha256(
        f"{math_grade:g}_{history_grade:g}".encode("utf-8")
    ).hexdigest()


def hash_student_report(student: AlunoCSV) -> str:
    report_identity = "\x1f".join(
        (
            student.id_aluno,
            str(student.email).casefold(),
            student.nome,
            hash_grades(student.nota_matematica, student.nota_historia),
        )
    )
    return hashlib.sha256(report_identity.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class _StudentOutcome:
    status: Literal["cache", "in_progress", "success", "failure"]
    elapsed_seconds: float
    tokens: int = 0
    cost_usd: float = 0
    updated: bool = False
    used_fallback: bool = False
    line_number: int = 0
    email: str = ""
    error_type: str = ""
    error_message: str | None = None


def compose_report_message(student: AlunoCSV, summary: str) -> str:
    return (
        "Boletim do período letivo\n\n"
        f"Matemática: {student.nota_matematica:g}/20\n"
        f"História: {student.nota_historia:g}/20\n\n"
        f"{summary}\n"
    )


def _validation_errors(
    error: ValidationError, line_number: int
) -> list[RowValidationError]:
    return [
        RowValidationError(
            linha=line_number,
            campo=".".join(str(part) for part in issue["loc"]),
            mensagem=issue["msg"],
        )
        for issue in error.errors()
    ]


class RepositoryGate:
    """Tira o I/O síncrono do banco do event loop, uma chamada de cada vez.

    A sessão SQLAlchemy não suporta uso concorrente; o lock serializa o acesso
    e `to_thread` evita que uma consulta lenta bloqueie as chamadas ao LLM.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()

    async def __call__(self, method: Callable[..., T], *args: Any) -> T:
        async with self._lock:
            with span(f"db.{method.__name__}", level=logging.DEBUG):
                return await asyncio.to_thread(method, *args)


class ExecutionBudget:
    """Teto de custo por execução, com reserva antes de cada chamada ao LLM."""

    def __init__(self, max_cost_usd: float | None) -> None:
        self.max_cost_usd = max_cost_usd
        self.spent_usd = 0.0
        self._reserved_usd = 0.0
        self.exhausted = False
        self._lock = threading.Lock()

    def reserve(self, amount: float) -> bool:
        with self._lock:
            if self.max_cost_usd is None:
                self._reserved_usd += amount
                return True
            if self.spent_usd + self._reserved_usd + amount > self.max_cost_usd:
                first_time = not self.exhausted
                self.exhausted = True
                if first_time:
                    log_event(
                        logger,
                        "grade_report.budget.exhausted",
                        logging.WARNING,
                        max_cost_usd=self.max_cost_usd,
                        spent_usd=round(self.spent_usd, 8),
                    )
                return False
            self._reserved_usd += amount
            return True

    def settle(self, reserved: float, actual: float) -> None:
        with self._lock:
            self._reserved_usd -= reserved
            self.spent_usd += actual


class BudgetedSummarizer(ISummarizer):
    """Antes de cada chamada reserva o custo máximo; sem saldo, usa o template."""

    def __init__(self, inner: ISummarizer, budget: ExecutionBudget) -> None:
        self.inner = inner
        self.budget = budget
        self.fallback = TemplateSummarizer()

    @property
    def provider_name(self) -> str:
        return self.inner.provider_name

    async def generate(self, student: AlunoCSV) -> SummaryResult:
        reserved = self.inner.estimate_max_cost(student)
        if not self.budget.reserve(reserved):
            result = await self.fallback.generate(student)
            return replace(result, used_fallback=True)
        actual = 0.0
        try:
            result = await self.inner.generate(student)
            actual = result.estimated_cost_usd
            return result
        finally:
            self.budget.settle(reserved, actual)


def max_cost_per_execution() -> float | None:
    raw = os.getenv("GRADE_MAX_COST_USD_PER_EXECUTION", "1.0").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError as error:
        raise ConfigurationError(
            "GRADE_MAX_COST_USD_PER_EXECUTION deve ser um número."
        ) from error
    if not math.isfinite(value) or value <= 0:
        raise ConfigurationError(
            "GRADE_MAX_COST_USD_PER_EXECUTION deve ser positivo (ou vazio)."
        )
    return value


def int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as error:
        raise ConfigurationError(f"{name} deve ser um inteiro.") from error
    if not minimum <= value <= maximum:
        raise ConfigurationError(f"{name} deve estar entre {minimum} e {maximum}.")
    return value


async def _process_student(
    line_number: int,
    student: AlunoCSV,
    db: RepositoryGate,
    repository: IGradeReportRepository,
    notifier: INotifier,
    summarizer: ISummarizer,
    execution_id: str,
    lease_seconds: int,
) -> _StudentOutcome:
    started_at = time.perf_counter()
    summary_result: SummaryResult | None = None
    claimed = False
    with span("grade_report.student", line=line_number) as attributes:
        try:
            current_hash = hash_student_report(student)

            def already_sent(stored: Any) -> bool:
                return (
                    stored is not None
                    and stored.grades_hash == current_hash
                    and stored.notification_status == "sent"
                )

            if already_sent(await db(repository.get_report, student.id_aluno)):
                attributes["outcome"] = "cache"
                log_event(
                    logger,
                    "grade_report.student_skipped",
                    line=line_number,
                    reason="already_sent",
                )
                return _StudentOutcome(
                    status="cache",
                    elapsed_seconds=time.perf_counter() - started_at,
                )

            claimed = await db(
                repository.claim_report, student.id_aluno, execution_id, lease_seconds
            )
            if not claimed:
                attributes["outcome"] = "in_progress"
                log_event(
                    logger,
                    "grade_report.student_skipped",
                    line=line_number,
                    reason="claimed_by_another_execution",
                )
                return _StudentOutcome(
                    status="in_progress",
                    elapsed_seconds=time.perf_counter() - started_at,
                )

            # Releitura após a reserva: outra execução pode ter acabado agora.
            stored_report = await db(repository.get_report, student.id_aluno)
            if already_sent(stored_report):
                attributes["outcome"] = "cache"
                return _StudentOutcome(
                    status="cache",
                    elapsed_seconds=time.perf_counter() - started_at,
                )

            await db(repository.upsert_student, student)
            was_updated = False
            if (
                stored_report is not None
                and stored_report.grades_hash == current_hash
                and stored_report.summary
            ):
                summary = stored_report.summary
                tokens = 0
                cost_usd = 0.0
            else:
                summary_result = await summarizer.generate(student)
                summary = summary_result.summary
                tokens = (
                    summary_result.prompt_tokens + summary_result.completion_tokens
                )
                cost_usd = summary_result.estimated_cost_usd
                was_updated = await db(
                    repository.save_report, student, current_hash, summary, tokens
                )

            await notifier.send_notification(
                str(student.email), compose_report_message(student, summary)
            )
            await db(repository.mark_report_notified, student.id_aluno)
            elapsed_seconds = time.perf_counter() - started_at
            used_fallback = bool(summary_result and summary_result.used_fallback)
            attributes.update(outcome="sent", tokens=tokens, fallback=used_fallback)
            log_event(
                logger,
                "grade_report.student_processed",
                line=line_number,
                summary_reused=summary_result is None,
                used_fallback=used_fallback,
                tokens=tokens,
                duration_ms=round(elapsed_seconds * 1000, 2),
            )
            return _StudentOutcome(
                status="success",
                elapsed_seconds=elapsed_seconds,
                tokens=tokens,
                cost_usd=cost_usd,
                updated=bool(summary_result and was_updated),
                used_fallback=used_fallback,
            )
        except Exception as error:
            email = str(student.email)
            # Apenas erros esperados: mensagens controladas e sem PII.
            error_message = str(error) if isinstance(error, _SAFE_ERRORS) else None
            attributes.update(outcome="failed", error_type=type(error).__name__)
            log_event(
                logger,
                "grade_report.student_failed",
                logging.WARNING,
                line=line_number,
                recipient=mask_email(email),
                error_type=type(error).__name__,
                error_message=error_message,
                duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
            )
            return _StudentOutcome(
                status="failure",
                elapsed_seconds=time.perf_counter() - started_at,
                tokens=(
                    summary_result.prompt_tokens + summary_result.completion_tokens
                    if summary_result
                    else 0
                ),
                cost_usd=summary_result.estimated_cost_usd if summary_result else 0,
                line_number=line_number,
                email=mask_email(email),
                error_type=type(error).__name__,
                error_message=error_message,
            )
        finally:
            if claimed:
                try:
                    await db(
                        repository.release_report, student.id_aluno, execution_id
                    )
                except Exception as error:  # o lease expira sozinho
                    log_event(
                        logger,
                        "grade_report.release_failed",
                        logging.WARNING,
                        line=line_number,
                        error_type=type(error).__name__,
                    )


def max_concurrent_students() -> int:
    return int_env("GRADE_MAX_CONCURRENCY", 5, 1, 50)


_percentile = percentile


def new_execution_id() -> str:
    return uuid.uuid4().hex


async def process_csv(
    content: bytes,
    repository: IGradeReportRepository,
    notifier: INotifier,
    summarizer: ISummarizer | None = None,
    execution_id: str | None = None,
) -> UploadReport:
    started_at = time.perf_counter()
    execution_id = execution_id or new_execution_id()
    context_token = execution_id_var.set(execution_id)
    try:
        with span("grade_report.execution"):
            return await _process_csv(
                content, repository, notifier, summarizer, execution_id, started_at
            )
    finally:
        execution_id_var.reset(context_token)


async def _process_csv(
    content: bytes,
    repository: IGradeReportRepository,
    notifier: INotifier,
    summarizer: ISummarizer | None,
    execution_id: str,
    started_at: float,
) -> UploadReport:
    base_summarizer = summarizer or MockSummarizer()
    concurrency = max_concurrent_students()
    lease_seconds = int_env("GRADE_PROCESSING_LEASE_SECONDS", 300, 30, 3600)
    budget = ExecutionBudget(max_cost_per_execution())
    budgeted_summarizer = BudgetedSummarizer(base_summarizer, budget)
    with span("grade_report.parse") as parse_attributes:
        try:
            frame = pd.read_csv(
                io.BytesIO(content),
                encoding="utf-8-sig",
                dtype=str,
                keep_default_na=False,
                skip_blank_lines=False,
            )
        except (pd.errors.EmptyDataError, pd.errors.ParserError) as error:
            raise ValueError("O ficheiro não contém um CSV válido.") from error
        parse_attributes["rows"] = len(frame)

    report = UploadReport(execution_id=execution_id, total_linhas=len(frame))
    log_event(
        logger, "grade_report.execution.started", total_rows=report.total_linhas
    )
    required_columns = {
        "id_aluno",
        "nome",
        "email",
        "nota_matematica",
        "nota_historia",
    }
    missing_columns = required_columns - set(frame.columns)
    if missing_columns and frame.empty:
        report.falhas_validacao += 1
        report.falhas += 1
        report.erros.extend(
            RowValidationError(
                linha=1,
                campo=column,
                mensagem="Coluna obrigatória ausente no cabeçalho.",
            )
            for column in sorted(missing_columns)
        )
    seen_student_ids: set[str] = set()
    seen_student_emails: set[str] = set()
    valid_students: list[tuple[int, AlunoCSV]] = []
    for index, row in frame.iterrows():
        line_number = int(index) + 2
        if missing_columns:
            report.falhas += 1
            report.falhas_validacao += 1
            report.erros.extend(
                RowValidationError(
                    linha=line_number,
                    campo=column,
                    mensagem="Coluna obrigatória ausente no cabeçalho.",
                )
                for column in sorted(missing_columns)
            )
            continue
        try:
            student = AlunoCSV.model_validate(row.to_dict())
        except ValidationError as error:
            report.falhas += 1
            report.falhas_validacao += 1
            report.erros.extend(_validation_errors(error, line_number))
            continue

        email_key = str(student.email).casefold()
        if (
            student.id_aluno in seen_student_ids
            or email_key in seen_student_emails
        ):
            report.duplicados_ignorados += 1
            continue
        seen_student_ids.add(student.id_aluno)
        seen_student_emails.add(email_key)
        valid_students.append((line_number, student))

    # Semáforo em vez de lotes fixos: um aluno lento não bloqueia o lote todo.
    semaphore = asyncio.Semaphore(concurrency)
    db = RepositoryGate()

    async def bounded(line_number: int, student: AlunoCSV) -> _StudentOutcome:
        async with semaphore:
            return await _process_student(
                line_number,
                student,
                db,
                repository,
                notifier,
                budgeted_summarizer,
                execution_id,
                lease_seconds,
            )

    outcomes = await asyncio.gather(
        *(bounded(line_number, student) for line_number, student in valid_students)
    )
    processing_times_ms: list[float] = []
    for outcome in outcomes:
        if outcome.status in ("success", "failure"):
            processing_times_ms.append(outcome.elapsed_seconds * 1000)
        if outcome.status == "cache":
            report.ignorados_cache += 1
        elif outcome.status == "in_progress":
            report.em_processamento += 1
        elif outcome.status == "success":
            report.processados += 1
            report.tokens_gastos += outcome.tokens
            report.custo_estimado_usd += outcome.cost_usd
            report.atualizados += int(outcome.updated)
            report.fallbacks_llm += int(outcome.used_fallback)
        else:
            report.falhas += 1
            report.falhas_processamento += 1
            report.tokens_gastos += outcome.tokens
            report.custo_estimado_usd += outcome.cost_usd
            cause = outcome.error_type
            if outcome.error_message:
                cause = f"{cause}: {outcome.error_message}"
            report.erros.append(
                RowValidationError(
                    linha=outcome.line_number,
                    campo="processamento",
                    mensagem=(
                        "Não foi possível processar o aluno "
                        f"{outcome.email} ({cause})."
                    ),
                )
            )

    report.orcamento_excedido = budget.exhausted
    report.summary_provider = base_summarizer.provider_name
    report.notification_provider = notifier.provider_name
    report.tempo_total_ms = (time.perf_counter() - started_at) * 1000
    if processing_times_ms:
        report.tempo_medio_processamento_ms = sum(processing_times_ms) / len(
            processing_times_ms
        )
        report.tempo_p95_processamento_ms = _percentile(processing_times_ms, 95)
    report.custo_estimado_usd = round(report.custo_estimado_usd, 8)
    log_event(
        logger,
        "grade_report.execution.completed",
        total_rows=report.total_linhas,
        processed=report.processados,
        failures=report.falhas,
        validation_failures=report.falhas_validacao,
        processing_failures=report.falhas_processamento,
        duplicates_skipped=report.duplicados_ignorados,
        cache_hits=report.ignorados_cache,
        in_progress_elsewhere=report.em_processamento,
        llm_fallbacks=report.fallbacks_llm,
        budget_exhausted=report.orcamento_excedido,
        tokens=report.tokens_gastos,
        estimated_cost_usd=report.custo_estimado_usd,
        duration_ms=round(report.tempo_total_ms, 2),
        avg_student_ms=round(report.tempo_medio_processamento_ms, 2),
        p95_student_ms=round(report.tempo_p95_processamento_ms, 2),
        summary_provider=report.summary_provider,
        notification_provider=report.notification_provider,
    )
    return report
