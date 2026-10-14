import time
from typing import Any

from sqlalchemy import case, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.exceptions import RosterConflictError
from app.interfaces.interfaces import IGradeReportRepository, StoredGradeReport
from app.models import (
    GradeReportExecutionModel,
    GradeReportModel,
    ReviewRequestModel,
    StudentModel,
)
from app.schemas.reports import (
    AlunoCSV,
    ExecutionRecord,
    DispatcherMetrics,
    UploadReport,
)


class ReportRepository(IGradeReportRepository):
    def __init__(self, db: Session) -> None:
        self.db = db

    def count_reports_and_pending_reviews(self) -> tuple[int, int]:
        total = self.db.scalar(
            select(func.count())
            .select_from(GradeReportModel)
            .where(GradeReportModel.hash_notas.is_not(None))
        )
        pending = self.db.scalar(
            select(func.count())
            .select_from(ReviewRequestModel)
            .where(ReviewRequestModel.status == "pending")
        )
        return total or 0, pending or 0

    def get_report(self, student_id: str) -> StoredGradeReport | None:
        report = self.db.get(GradeReportModel, student_id)
        if report is None:
            return None
        return StoredGradeReport(
            grades_hash=report.hash_notas,
            summary=report.resumo_llm,
            tokens=report.tokens_gastos,
            notification_status=report.status_notificacao,
        )

    def save_report(
        self, student: AlunoCSV, grades_hash: str, summary: str, tokens: int
    ) -> bool:
        report = self.db.get(GradeReportModel, student.id_aluno)
        updated = report is not None
        if report is None:
            report = GradeReportModel(id_aluno=student.id_aluno)
            self.db.add(report)

        report.nome = student.nome
        report.email = str(student.email)
        report.hash_notas = grades_hash
        report.resumo_llm = summary
        report.nota_matematica = student.nota_matematica
        report.nota_historia = student.nota_historia
        report.tokens_gastos = tokens
        report.status_notificacao = "pending"
        if updated:
            report.status_revisao = False
        self.db.commit()
        return updated

    def upsert_student(self, student: AlunoCSV) -> None:
        email = str(student.email).strip().casefold()
        record_by_id = self.db.get(StudentModel, student.id_aluno)
        email_owner = self.db.scalar(
            select(StudentModel).where(StudentModel.email == email)
        )
        if (
            record_by_id is not None
            and email_owner is not None
            and email_owner is not record_by_id
        ):
            raise RosterConflictError("O email já pertence a outro aluno do cadastro.")
        # Mesma política da massa inicial: sem o UUID, o email identifica o aluno.
        record = record_by_id or email_owner
        if record is None:
            # A conta de acesso é provisionada pelo cadastro ou no arranque.
            self.db.add(
                StudentModel(
                    student_id=student.id_aluno,
                    name=student.nome,
                    email=email,
                    math_grade=student.nota_matematica,
                    history_grade=student.nota_historia,
                    review_requested=False,
                )
            )
        elif record.email != email:
            raise RosterConflictError(
                "O email difere do cadastro; altere-o pelo cadastro de alunos."
            )
        else:
            record.name = student.nome
            record.math_grade = student.nota_matematica
            record.history_grade = student.nota_historia
        self.db.commit()

    def mark_report_notified(self, student_id: str) -> None:
        report = self.db.get(GradeReportModel, student_id)
        if report is None:
            raise LookupError("Boletim não encontrado para confirmar o envio.")
        report.status_notificacao = "sent"
        self.db.commit()

    def claim_report(self, student_id: str, owner: str, lease_seconds: int) -> bool:
        now = int(time.time())
        if self.db.get(GradeReportModel, student_id) is None:
            # O primeiro a inserir ganha; a PK impede uma segunda inserção.
            self.db.add(
                GradeReportModel(
                    id_aluno=student_id,
                    processing_owner=owner,
                    processing_until=now + lease_seconds,
                )
            )
            try:
                self.db.commit()
                return True
            except IntegrityError:
                self.db.rollback()
        # UPDATE condicional e atómico: só reserva se não houver lease válido.
        result = self.db.execute(
            update(GradeReportModel)
            .where(
                GradeReportModel.id_aluno == student_id,
                or_(
                    GradeReportModel.processing_until.is_(None),
                    GradeReportModel.processing_until < now,
                    GradeReportModel.processing_owner == owner,
                ),
            )
            .values(processing_owner=owner, processing_until=now + lease_seconds)
            .execution_options(synchronize_session=False)
        )
        self.db.commit()
        self.db.expire_all()
        return result.rowcount == 1

    def release_report(self, student_id: str, owner: str) -> None:
        self.db.execute(
            update(GradeReportModel)
            .where(
                GradeReportModel.id_aluno == student_id,
                GradeReportModel.processing_owner == owner,
            )
            .values(processing_owner=None, processing_until=None)
            .execution_options(synchronize_session=False)
        )
        self.db.commit()
        self.db.expire_all()

    def start_execution(
        self, execution_id: str, *, summary_provider: str, notification_provider: str
    ) -> None:
        self.db.add(
            GradeReportExecutionModel(
                execution_id=execution_id,
                status="running",
                total_linhas=0,
                processados=0,
                falhas=0,
                tokens_gastos=0,
                custo_estimado_usd=0,
                tempo_total_ms=0,
                tempo_medio_processamento_ms=0,
                summary_provider=summary_provider,
                notification_provider=notification_provider,
            )
        )
        self.db.commit()

    def fail_execution(self, execution_id: str, message: str) -> None:
        execution = self._execution(execution_id)
        if execution is not None:
            execution.status = "failed"
            execution.erro = message
            self.db.commit()

    def record_execution(
        self,
        report: UploadReport,
        *,
        summary_provider: str,
        notification_provider: str,
    ) -> None:
        execution = (
            self._execution(report.execution_id) if report.execution_id else None
        )
        if execution is None:
            execution = GradeReportExecutionModel(
                execution_id=report.execution_id or None
            )
            self.db.add(execution)
        execution.status = "completed"
        execution.total_linhas = report.total_linhas
        execution.processados = report.processados
        execution.falhas = report.falhas
        execution.tokens_gastos = report.tokens_gastos
        execution.custo_estimado_usd = report.custo_estimado_usd
        execution.tempo_total_ms = report.tempo_total_ms
        execution.tempo_medio_processamento_ms = report.tempo_medio_processamento_ms
        execution.tempo_p95_processamento_ms = report.tempo_p95_processamento_ms
        execution.ignorados_cache = report.ignorados_cache
        execution.duplicados_ignorados = report.duplicados_ignorados
        execution.falhas_validacao = report.falhas_validacao
        execution.falhas_processamento = report.falhas_processamento
        execution.fallbacks_llm = report.fallbacks_llm
        execution.em_processamento = report.em_processamento
        execution.orcamento_excedido = report.orcamento_excedido
        execution.summary_provider = summary_provider
        execution.notification_provider = notification_provider
        self.db.commit()

    def _execution(self, execution_id: str) -> GradeReportExecutionModel | None:
        return self.db.scalar(
            select(GradeReportExecutionModel).where(
                GradeReportExecutionModel.execution_id == execution_id
            )
        )

    def get_execution(self, execution_id: str) -> ExecutionRecord | None:
        execution = self._execution(execution_id)
        return ExecutionRecord.model_validate(execution) if execution else None

    def list_executions(self, limit: int) -> list[ExecutionRecord]:
        executions = self.db.scalars(
            select(GradeReportExecutionModel)
            .order_by(GradeReportExecutionModel.id.desc())
            .limit(limit)
        ).all()
        return [ExecutionRecord.model_validate(item) for item in executions]

    def summarize_executions(self) -> DispatcherMetrics:
        table = GradeReportExecutionModel
        completed = table.status == "completed"
        attempted_per_execution = table.processados + table.falhas_processamento

        def total(column: Any) -> Any:
            return func.coalesce(func.sum(column), 0)

        row = self.db.execute(
            select(
                func.count(),
                total(table.total_linhas),
                total(table.processados),
                total(table.falhas),
                total(table.falhas_validacao),
                total(table.falhas_processamento),
                total(table.duplicados_ignorados),
                total(table.ignorados_cache),
                total(table.fallbacks_llm),
                total(case((table.orcamento_excedido.is_(True), 1), else_=0)),
                total(table.tokens_gastos),
                total(table.custo_estimado_usd),
                # Média por aluno ponderada pelo número de alunos de cada execução.
                total(table.tempo_medio_processamento_ms * attempted_per_execution),
                func.coalesce(func.max(table.tempo_p95_processamento_ms), 0),
                func.coalesce(func.avg(table.tempo_total_ms), 0),
                func.max(table.created_at),
            ).where(completed)
        ).one()
        (
            executions,
            rows_received,
            processed,
            failures,
            validation_failures,
            processing_failures,
            duplicates,
            cache_hits,
            fallbacks,
            budget_exhausted,
            tokens,
            cost,
            weighted_ms,
            max_p95_ms,
            avg_pipeline_ms,
            last_execution,
        ) = row
        status_counts = dict(
            self.db.execute(
                select(table.status, func.count()).group_by(table.status)
            ).all()
        )
        attempted = processed + processing_failures

        def ratio(part: float, whole: float) -> float:
            return round(part / whole, 4) if whole else 0

        return DispatcherMetrics(
            execucoes=executions,
            execucoes_em_andamento=status_counts.get("running", 0),
            execucoes_com_falha=status_counts.get("failed", 0),
            ultima_execucao_em=last_execution,
            linhas_recebidas=rows_received,
            alunos_processados=processed,
            falhas=failures,
            falhas_validacao=validation_failures,
            falhas_processamento=processing_failures,
            duplicados_ignorados=duplicates,
            ignorados_cache=cache_hits,
            taxa_falha_processamento=ratio(processing_failures, attempted),
            taxa_cache=ratio(cache_hits, attempted + cache_hits),
            fallbacks_llm=fallbacks,
            taxa_fallback=ratio(fallbacks, processed),
            execucoes_com_orcamento_excedido=budget_exhausted,
            tokens_gastos=tokens,
            custo_estimado_usd=round(cost, 8),
            custo_medio_por_aluno_usd=round(cost / processed, 8) if processed else 0,
            tempo_medio_processamento_ms=(
                round(weighted_ms / attempted, 2) if attempted else 0
            ),
            pior_p95_processamento_ms=round(max_p95_ms, 2),
            tempo_medio_pipeline_ms=round(avg_pipeline_ms, 2),
        )
