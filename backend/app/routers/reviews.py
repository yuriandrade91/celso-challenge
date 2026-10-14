from collections.abc import Sequence

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, require_teacher
from app.database import get_db
from app.domain.review_exceptions import (
    ReviewRequestConflictError,
    ReviewRequestNotFoundError,
)
from app.models import ReviewRequestModel, StudentModel
from app.repositories.reviews import ReviewRepository
from app.schemas.auth import AuthenticatedUser
from app.schemas.responses import ApiResponse
from app.schemas.reviews import (
    ReviewDecision,
    ReviewRequestCreate,
    ReviewRequestResponse,
)
from app.services.notifications import MockStudentNotifier
from app.services.reviews import ReviewService

router = APIRouter(prefix="/reviews", tags=["Grade Reviews"])


def get_review_service(db: Session = Depends(get_db)) -> ReviewService:
    return ReviewService(ReviewRepository(db), MockStudentNotifier())


def to_review_response(
    item: tuple[ReviewRequestModel, StudentModel],
) -> ReviewRequestResponse:
    review, student = item
    return ReviewRequestResponse(
        id=review.id,
        student_id=student.student_id,
        student_name=student.name,
        student_email=student.email,
        subject=review.subject,
        justification=review.justification,
        original_grade=review.original_grade,
        status=review.status,
        teacher_response=review.teacher_response,
        adjusted_grade=review.adjusted_grade,
        created_at=review.created_at,
        decided_at=review.decided_at,
    )


def review_responses(
    reviews: Sequence[tuple[ReviewRequestModel, StudentModel]],
) -> list[ReviewRequestResponse]:
    return [to_review_response(review) for review in reviews]


@router.post(
    "/",
    response_model=ApiResponse[ReviewRequestResponse],
    status_code=status.HTTP_201_CREATED,
)
def create_review(
    request: ReviewRequestCreate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: ReviewService = Depends(get_review_service),
) -> ApiResponse[ReviewRequestResponse]:
    if current_user.role != "student" or current_user.student_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas estudantes podem solicitar revisão.",
        )
    try:
        review = service.request_review(current_user.student_id, request)
    except ReviewRequestConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return ApiResponse(success=True, data=to_review_response(review))


@router.get(
    "/me",
    response_model=ApiResponse[list[ReviewRequestResponse]],
)
def get_own_reviews(
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: ReviewService = Depends(get_review_service),
) -> ApiResponse[list[ReviewRequestResponse]]:
    if current_user.role != "student" or current_user.student_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas estudantes podem consultar os seus pedidos.",
        )
    return ApiResponse(
        success=True,
        data=review_responses(service.get_student_reviews(current_user.student_id)),
    )


@router.get(
    "/",
    response_model=ApiResponse[list[ReviewRequestResponse]],
)
def get_pending_reviews(
    service: ReviewService = Depends(get_review_service),
    _: AuthenticatedUser = Depends(require_teacher),
) -> ApiResponse[list[ReviewRequestResponse]]:
    return ApiResponse(success=True, data=review_responses(service.get_pending_reviews()))


@router.patch(
    "/{review_id}/decision",
    response_model=ApiResponse[ReviewRequestResponse],
)
def decide_review(
    review_id: int,
    decision: ReviewDecision,
    service: ReviewService = Depends(get_review_service),
    _: AuthenticatedUser = Depends(require_teacher),
) -> ApiResponse[ReviewRequestResponse]:
    try:
        review = service.decide_review(review_id, decision)
    except ReviewRequestNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="O pedido de revisão não foi encontrado.",
        ) from error
    except ReviewRequestConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error
    return ApiResponse(success=True, data=to_review_response(review))


@router.delete(
    "/{review_id}",
    response_model=ApiResponse[None],
)
def delete_pending_review(
    review_id: int,
    service: ReviewService = Depends(get_review_service),
    _: AuthenticatedUser = Depends(require_teacher),
) -> ApiResponse[None]:
    try:
        service.delete_pending_review(review_id)
    except ReviewRequestNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="O pedido de revisão não foi encontrado.",
        ) from error
    except ReviewRequestConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error
    return ApiResponse(success=True, data=None)
