from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import require_teacher
from app.database import get_db
from app.repositories.reports import ReportRepository
from app.schemas.auth import AuthenticatedUser
from app.schemas.reports import Metrics
from app.schemas.responses import ApiResponse
from app.services.dashboard import dashboard_metrics

router = APIRouter(tags=["Metrics"])


@router.get(
    "/metrics",
    response_model=ApiResponse[Metrics],
    summary="Métricas do painel: dispatcher, operação e últimas execuções",
)
def get_metrics(
    recent: int = Query(default=5, ge=0, le=50, description="Execuções recentes"),
    db: Session = Depends(get_db),
    _: AuthenticatedUser = Depends(require_teacher),
) -> ApiResponse[Metrics]:
    return ApiResponse(
        success=True, data=dashboard_metrics(ReportRepository(db), recent)
    )
