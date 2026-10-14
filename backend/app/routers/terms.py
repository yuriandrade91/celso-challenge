from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.dependencies import require_teacher
from app.database import get_db
from app.domain.exceptions import ConfigurationError
from app.domain.term_exceptions import TermConflictError
from app.rate_limit import limit_term_close
from app.repositories.terms import TermRepository
from app.schemas.auth import AuthenticatedUser
from app.schemas.responses import ApiResponse
from app.schemas.terms import (
    TermCloseReport,
    TermCreate,
    TermDelivery,
    TermResponse,
    TermUpdate,
)
from app.services.providers import create_grade_report_notifier, create_summarizer
from app.services.terms import TermBusyError, close_term

router = APIRouter(prefix="/terms", tags=["Academic Terms"])
_NOT_FOUND = "Semestre não encontrado."


@router.get("", response_model=ApiResponse[list[TermResponse]])
def list_terms(
    db: Session = Depends(get_db),
    _: AuthenticatedUser = Depends(require_teacher),
) -> ApiResponse[list[TermResponse]]:
    return ApiResponse(success=True, data=TermRepository(db).list_terms())


@router.post(
    "",
    response_model=ApiResponse[TermResponse],
    status_code=status.HTTP_201_CREATED,
)
def create_term(
    term: TermCreate,
    db: Session = Depends(get_db),
    _: AuthenticatedUser = Depends(require_teacher),
) -> ApiResponse[TermResponse]:
    try:
        return ApiResponse(success=True, data=TermRepository(db).create_term(term))
    except TermConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.put("/{term_id}", response_model=ApiResponse[TermResponse])
def update_term(
    term_id: int,
    term: TermUpdate,
    db: Session = Depends(get_db),
    _: AuthenticatedUser = Depends(require_teacher),
) -> ApiResponse[TermResponse]:
    try:
        updated = TermRepository(db).update_term(term_id, term)
    except TermConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if updated is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return ApiResponse(success=True, data=updated)


@router.delete("/{term_id}", response_model=ApiResponse[None])
def delete_term(
    term_id: int,
    db: Session = Depends(get_db),
    _: AuthenticatedUser = Depends(require_teacher),
) -> ApiResponse[None]:
    try:
        deleted = TermRepository(db).delete_term(term_id)
    except TermConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if not deleted:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return ApiResponse(success=True, data=None)


@router.post(
    "/{term_id}/close",
    response_model=ApiResponse[TermCloseReport],
    summary="Fecha o semestre e notifica cada aluno com o resumo do LLM",
)
async def close_academic_term(
    term_id: int,
    db: Session = Depends(get_db),
    current_user: AuthenticatedUser = Depends(limit_term_close),
) -> ApiResponse[TermCloseReport]:
    try:
        notifier, summarizer = create_grade_report_notifier(), create_summarizer()
        report = await close_term(
            term_id, TermRepository(db), notifier, summarizer, current_user.email
        )
    except ConfigurationError as error:
        raise HTTPException(
            status_code=503, detail=f"Configuração do servidor inválida: {error}"
        ) from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=_NOT_FOUND) from error
    except TermBusyError as error:
        raise HTTPException(
            status_code=409, detail="O fecho deste semestre já está em andamento."
        ) from error
    return ApiResponse(success=True, data=report)


@router.get(
    "/{term_id}/notifications",
    response_model=ApiResponse[list[TermDelivery]],
)
def list_term_deliveries(
    term_id: int,
    db: Session = Depends(get_db),
    _: AuthenticatedUser = Depends(require_teacher),
) -> ApiResponse[list[TermDelivery]]:
    repository = TermRepository(db)
    if repository.get_term_snapshot(term_id) is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return ApiResponse(success=True, data=repository.deliveries(term_id))
