import asyncio
import logging
import os
from collections.abc import Callable
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.auth.dependencies import require_teacher
from app.database import get_db, get_session_factory
from app.domain.exceptions import ConfigurationError
from app.interfaces.interfaces import INotifier, ISummarizer
from app.observability import log_event
from app.rate_limit import limit_upload
from app.repositories.reports import ReportRepository
from app.schemas.auth import AuthenticatedUser
from app.schemas.reports import (
    AsyncUploadAccepted,
    ExecutionRecord,
    UploadReport,
)
from app.schemas.responses import ApiResponse
from app.services.providers import (
    create_grade_report_notifier,
    create_summarizer,
)
from app.services.reports import new_execution_id, process_csv

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Grade Report Dispatcher"])
# Referências fortes: o asyncio só guarda referências fracas às tarefas.
_BACKGROUND_TASKS: set[asyncio.Task[None]] = set()


async def _read_csv_upload(file: UploadFile) -> bytes:
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Apenas CSV")
    try:
        max_size_mb = int(os.getenv("GRADE_MAX_UPLOAD_SIZE_MB", "10"))
    except ValueError as error:
        raise HTTPException(
            status_code=503,
            detail="GRADE_MAX_UPLOAD_SIZE_MB deve ser um inteiro.",
        ) from error
    if not 1 <= max_size_mb <= 100:
        raise HTTPException(
            status_code=503,
            detail="GRADE_MAX_UPLOAD_SIZE_MB deve estar entre 1 e 100.",
        )
    max_size_bytes = max_size_mb * 1024 * 1024
    content = await file.read(max_size_bytes + 1)
    if len(content) > max_size_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"O CSV excede o limite de {max_size_mb} MB.",
        )
    try:
        content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise HTTPException(
            status_code=400,
            detail="O ficheiro CSV deve utilizar a codificação UTF-8.",
        ) from error
    return content


def _providers() -> tuple[INotifier, ISummarizer]:
    try:
        return create_grade_report_notifier(), create_summarizer()
    except ConfigurationError as error:
        raise HTTPException(
            status_code=503, detail=f"Configuração do servidor inválida: {error}"
        ) from error


async def _run_in_background(
    content: bytes,
    execution_id: str,
    session_factory: Callable[[], Session],
    notifier: INotifier,
    summarizer: ISummarizer,
) -> None:
    """Executa o dispatch fora do pedido HTTP, com uma sessão própria."""
    with session_factory() as db:
        repository = ReportRepository(db)
        try:
            report = await process_csv(
                content, repository, notifier, summarizer, execution_id
            )
        except Exception as error:
            message = (
                str(error)
                if isinstance(error, ValueError)
                else "Erro inesperado; consulte os logs pelo execution_id."
            )
            log_event(
                logger,
                "grade_report.execution.failed",
                logging.ERROR,
                error_type=type(error).__name__,
            )
            await asyncio.to_thread(repository.fail_execution, execution_id, message)
            return
        await asyncio.to_thread(
            repository.record_execution,
            report,
            summary_provider=report.summary_provider,
            notification_provider=report.notification_provider,
        )


@router.post(
    "/upload",
    response_model=ApiResponse[UploadReport],
    responses={202: {"model": ApiResponse[AsyncUploadAccepted]}},
)
async def upload_grades(
    file: UploadFile = File(...),
    mode: Literal["sync", "async"] = Query(
        default="sync",
        description=(
            "sync devolve o relatório no próprio pedido; async responde 202 e "
            "processa em segundo plano (consultar GET /executions/{id})."
        ),
    ),
    db: Session = Depends(get_db),
    session_factory: Callable[[], Session] = Depends(get_session_factory),
    _: AuthenticatedUser = Depends(limit_upload),
) -> ApiResponse[UploadReport] | JSONResponse:
    content = await _read_csv_upload(file)
    notifier, summarizer = _providers()
    repository = ReportRepository(db)
    execution_id = new_execution_id()

    if mode == "async":
        repository.start_execution(
            execution_id,
            summary_provider=summarizer.provider_name,
            notification_provider=notifier.provider_name,
        )
        task = asyncio.create_task(
            _run_in_background(
                content, execution_id, session_factory, notifier, summarizer
            )
        )
        _BACKGROUND_TASKS.add(task)
        task.add_done_callback(_BACKGROUND_TASKS.discard)
        body = ApiResponse(
            success=True,
            data=AsyncUploadAccepted(execution_id=execution_id, status="running"),
        )
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content=body.model_dump(by_alias=True, mode="json"),
            headers={"Location": f"/executions/{execution_id}"},
        )

    try:
        report = await process_csv(
            content, repository, notifier, summarizer, execution_id
        )
    except ConfigurationError as error:
        raise HTTPException(
            status_code=503, detail=f"Configuração do servidor inválida: {error}"
        ) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    repository.record_execution(
        report,
        summary_provider=report.summary_provider,
        notification_provider=report.notification_provider,
    )
    return ApiResponse(success=True, data=report)


@router.get("/executions", response_model=ApiResponse[list[ExecutionRecord]])
def list_executions(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: AuthenticatedUser = Depends(require_teacher),
) -> ApiResponse[list[ExecutionRecord]]:
    return ApiResponse(success=True, data=ReportRepository(db).list_executions(limit))


@router.get("/executions/{execution_id}", response_model=ApiResponse[ExecutionRecord])
def get_execution(
    execution_id: str,
    db: Session = Depends(get_db),
    _: AuthenticatedUser = Depends(require_teacher),
) -> ApiResponse[ExecutionRecord]:
    execution = ReportRepository(db).get_execution(execution_id)
    if execution is None:
        raise HTTPException(status_code=404, detail="Execução não encontrada.")
    return ApiResponse(success=True, data=execution)
