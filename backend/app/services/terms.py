import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Literal

from pydantic import ValidationError

from app.interfaces.interfaces import (
    INotifier,
    ISummarizer,
    ITermClosingRepository,
    RosterStudent,
    TermSnapshot,
)
from app.observability import execution_id_var, log_event, span
from app.schemas.reports import AlunoCSV, RowValidationError
from app.schemas.terms import TermCloseReport
from app.services.notifications import mask_email
from app.services.providers import ProviderRequestError
from app.services.reports import (
    BudgetedSummarizer,
    ExecutionBudget,
    RepositoryGate,
    hash_student_report,
    int_env,
    max_concurrent_students,
    max_cost_per_execution,
    new_execution_id,
)

logger = logging.getLogger(__name__)


class TermBusyError(Exception):
    """Outro fecho do mesmo semestre está em andamento."""


@dataclass(frozen=True)
class _Outcome:
    status: Literal["notified", "already_notified", "failure"]
    reused_summary: bool = False
    used_fallback: bool = False
    tokens: int = 0
    cost_usd: float = 0
    error: str | None = None


def notification_title(term: TermSnapshot) -> str:
    return f"Boletim de {term.name}"


def compose_term_message(
    term: TermSnapshot, student: RosterStudent, summary: str
) -> str:
    return (
        f"Boletim de {term.name} ({term.code})\n\n"
        f"Matemática: {student.math_grade:g}/20\n"
        f"História: {student.history_grade:g}/20\n\n"
        f"{summary}\n"
    )


async def _notify_student(
    student: RosterStudent,
    term: TermSnapshot,
    db: RepositoryGate,
    repository: ITermClosingRepository,
    notifier: INotifier,
    summarizer: ISummarizer,
) -> _Outcome:
    tokens = 0
    cost_usd = 0.0
    with span("term.student") as attributes:
        try:
            stored = await db(
                repository.get_notification, student.student_id, term.id
            )
            if stored is not None and stored.email_status == "sent":
                attributes["outcome"] = "already_notified"
                return _Outcome(status="already_notified")

            used_fallback = False
            if stored is not None:
                # Reenvio após falha: mantém o texto que o aluno já vê na app.
                notification_id, summary, reused = stored.id, stored.summary, True
            else:
                candidate = AlunoCSV(
                    id_aluno=student.student_id,
                    nome=student.name,
                    email=student.email,
                    nota_matematica=student.math_grade,
                    nota_historia=student.history_grade,
                )
                cached = await db(
                    repository.cached_summary,
                    candidate.id_aluno,
                    hash_student_report(candidate),
                )
                if cached:
                    summary, source, reused = cached, "cache", True
                else:
                    result = await summarizer.generate(candidate)
                    summary = result.summary
                    tokens = result.prompt_tokens + result.completion_tokens
                    cost_usd = result.estimated_cost_usd
                    used_fallback = result.used_fallback
                    source = "template" if used_fallback else "llm"
                    reused = False
                # A notificação in-app fica visível mesmo que o email falhe.
                notification_id = await db(
                    repository.save_notification,
                    term.id,
                    student,
                    notification_title(term),
                    summary,
                    source,
                    tokens,
                )

            try:
                await notifier.send_notification(
                    student.email, compose_term_message(term, student, summary)
                )
            except Exception:
                await db(repository.set_email_status, notification_id, "failed")
                raise
            await db(repository.set_email_status, notification_id, "sent")
            attributes.update(outcome="notified", tokens=tokens)
            return _Outcome(
                status="notified",
                reused_summary=reused,
                used_fallback=used_fallback,
                tokens=tokens,
                cost_usd=cost_usd,
            )
        except Exception as error:
            # Apenas erros esperados expõem a mensagem: nada de PII ou stack.
            if isinstance(error, ValidationError):
                reason = "dados do cadastro inválidos"
            elif isinstance(error, ProviderRequestError):
                reason = str(error)
            else:
                reason = type(error).__name__
            attributes.update(outcome="failed", error_type=type(error).__name__)
            log_event(
                logger,
                "term.student_failed",
                logging.WARNING,
                recipient=mask_email(student.email),
                error_type=type(error).__name__,
            )
            return _Outcome(
                status="failure",
                tokens=tokens,
                cost_usd=cost_usd,
                error=f"{mask_email(student.email)} ({reason})",
            )


async def close_term(
    term_id: int,
    repository: ITermClosingRepository,
    notifier: INotifier,
    summarizer: ISummarizer,
    closed_by: str,
    execution_id: str | None = None,
) -> TermCloseReport:
    """Fecha o semestre e entrega a cada aluno o boletim com resumo do LLM.

    Idempotente: alunos já notificados neste semestre são ignorados, e voltar a
    fechar um semestre fechado reenvia só as entregas que falharam (ou alunos
    novos). Lança LookupError se o semestre não existir e TermBusyError se
    outro fecho estiver ativo.
    """
    started_at = time.perf_counter()
    execution_id = execution_id or new_execution_id()
    context_token = execution_id_var.set(execution_id)
    db = RepositoryGate()
    try:
        with span("term.close", term_id=term_id):
            term = await db(repository.get_term_snapshot, term_id)
            if term is None:
                raise LookupError(term_id)
            lease_seconds = int_env("TERM_CLOSING_LEASE_SECONDS", 900, 60, 86_400)
            if not await db(
                repository.claim_closing, term_id, execution_id, lease_seconds
            ):
                raise TermBusyError()
            finished = False
            try:
                report = await _close_claimed_term(
                    term, db, repository, notifier, summarizer, execution_id
                )
                await db(repository.finish_closing, term_id, execution_id, closed_by)
                finished = True
            finally:
                if not finished:
                    await db(repository.abort_closing, term_id, execution_id)
            report.tempo_total_ms = (time.perf_counter() - started_at) * 1000
            log_event(
                logger,
                "term.closed",
                term_id=term_id,
                students=report.total_alunos,
                notified=report.notificados,
                already_notified=report.ja_notificados,
                failures=report.falhas,
                llm_fallbacks=report.fallbacks_llm,
                tokens=report.tokens_gastos,
                estimated_cost_usd=report.custo_estimado_usd,
                duration_ms=round(report.tempo_total_ms, 2),
            )
            return report
    finally:
        execution_id_var.reset(context_token)


async def _close_claimed_term(
    term: TermSnapshot,
    db: RepositoryGate,
    repository: ITermClosingRepository,
    notifier: INotifier,
    summarizer: ISummarizer,
    execution_id: str,
) -> TermCloseReport:
    budget = ExecutionBudget(max_cost_per_execution())
    budgeted = BudgetedSummarizer(summarizer, budget)
    semaphore = asyncio.Semaphore(max_concurrent_students())
    roster = await db(repository.roster)

    async def bounded(student: RosterStudent) -> _Outcome:
        async with semaphore:
            return await _notify_student(
                student, term, db, repository, notifier, budgeted
            )

    outcomes = await asyncio.gather(*(bounded(student) for student in roster))
    report = TermCloseReport(
        term_id=term.id,
        execution_id=execution_id,
        total_alunos=len(roster),
        summary_provider=summarizer.provider_name,
        notification_provider=notifier.provider_name,
    )
    for outcome in outcomes:
        report.tokens_gastos += outcome.tokens
        report.custo_estimado_usd += outcome.cost_usd
        if outcome.status == "already_notified":
            report.ja_notificados += 1
        elif outcome.status == "notified":
            report.notificados += 1
            report.resumos_reaproveitados += int(outcome.reused_summary)
            report.fallbacks_llm += int(outcome.used_fallback)
        else:
            report.falhas += 1
            report.erros.append(
                RowValidationError(
                    linha=0,
                    campo="entrega",
                    mensagem=f"Não foi possível notificar {outcome.error}.",
                )
            )
    report.orcamento_excedido = budget.exhausted
    report.custo_estimado_usd = round(report.custo_estimado_usd, 8)
    return report
