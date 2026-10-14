from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.repositories.terms import TermRepository
from app.schemas.auth import AuthenticatedUser
from app.schemas.responses import ApiResponse
from app.schemas.terms import StudentInbox

router = APIRouter(prefix="/notifications", tags=["Student Notifications"])


def require_student(
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> str:
    if current_user.role != "student" or current_user.student_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="A central de notificações está disponível apenas para estudantes.",
        )
    return current_user.student_id


@router.get("/me", response_model=ApiResponse[StudentInbox])
def get_own_notifications(
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    student_id: str = Depends(require_student),
) -> ApiResponse[StudentInbox]:
    return ApiResponse(success=True, data=TermRepository(db).inbox(student_id, limit))


@router.post("/me/read-all", response_model=ApiResponse[int])
def mark_all_notifications_read(
    db: Session = Depends(get_db),
    student_id: str = Depends(require_student),
) -> ApiResponse[int]:
    return ApiResponse(success=True, data=TermRepository(db).mark_all_read(student_id))


@router.patch("/{notification_id}/read", response_model=ApiResponse[None])
def mark_notification_read(
    notification_id: int,
    db: Session = Depends(get_db),
    student_id: str = Depends(require_student),
) -> ApiResponse[None]:
    # 404 também para notificações de outro aluno: não revela que existem.
    if not TermRepository(db).mark_read(notification_id, student_id):
        raise HTTPException(status_code=404, detail="Notificação não encontrada.")
    return ApiResponse(success=True, data=None)
