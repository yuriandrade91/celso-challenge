from math import ceil

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, require_teacher
from app.database import get_db
from app.repositories.students import SQLiteStudentRepository
from app.schemas.auth import AuthenticatedUser
from app.schemas.responses import ApiResponse, Pagination
from app.schemas.students import StudentCreate, StudentResponse, StudentUpdate
from app.services.notifications import MockStudentNotifier
from app.services.students import StudentAppService

router = APIRouter(prefix="/students", tags=["Students"])


def get_student_service(db: Session = Depends(get_db)) -> StudentAppService:
    repository = SQLiteStudentRepository(db)
    return StudentAppService(
        read_repo=repository,
        write_repo=repository,
        notifier=MockStudentNotifier(),
    )


@router.post(
    "/",
    response_model=ApiResponse[StudentResponse],
    status_code=status.HTTP_201_CREATED,
)
def create_student(
    student: StudentCreate,
    service: StudentAppService = Depends(get_student_service),
    _: AuthenticatedUser = Depends(require_teacher),
) -> ApiResponse[StudentResponse]:
    return ApiResponse(success=True, data=service.register_student(student))


@router.get("/", response_model=ApiResponse[list[StudentResponse]])
def get_students(
    page_number: int = Query(default=1, ge=1, alias="pageNumber"),
    page_size: int = Query(default=20, ge=1, le=100, alias="pageSize"),
    service: StudentAppService = Depends(get_student_service),
    _: AuthenticatedUser = Depends(require_teacher),
) -> ApiResponse[list[StudentResponse]]:
    students, total_records = service.get_students_page(page_number, page_size)
    total_pages = ceil(total_records / page_size)
    return ApiResponse(
        success=True,
        data=list(students),
        pagination=Pagination(
            page_number=page_number,
            page_size=page_size,
            total_records=total_records,
            total_pages=total_pages,
            has_next_page=page_number < total_pages,
            has_previous_page=page_number > 1 and total_pages > 0,
        ),
    )


@router.get(
    "/under-review",
    response_model=ApiResponse[list[StudentResponse]],
)
def get_students_under_review(
    service: StudentAppService = Depends(get_student_service),
    _: AuthenticatedUser = Depends(require_teacher),
) -> ApiResponse[list[StudentResponse]]:
    return ApiResponse(
        success=True,
        data=list(service.get_students_under_review()),
    )


@router.get("/me", response_model=ApiResponse[StudentResponse])
def get_own_student(
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: StudentAppService = Depends(get_student_service),
) -> ApiResponse[StudentResponse]:
    if current_user.role != "student" or current_user.student_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="O perfil de professor não possui um registo de estudante.",
        )
    return ApiResponse(success=True, data=service.get_student(current_user.student_id))


@router.get("/{student_id}", response_model=ApiResponse[StudentResponse])
def get_student(
    student_id: str,
    service: StudentAppService = Depends(get_student_service),
    _: AuthenticatedUser = Depends(require_teacher),
) -> ApiResponse[StudentResponse]:
    return ApiResponse(success=True, data=service.get_student(student_id))


@router.put("/{student_id}", response_model=ApiResponse[StudentResponse])
def update_student(
    student_id: str,
    student_update: StudentUpdate,
    service: StudentAppService = Depends(get_student_service),
    _: AuthenticatedUser = Depends(require_teacher),
) -> ApiResponse[StudentResponse]:
    return ApiResponse(
        success=True,
        data=service.update_student(student_id, student_update),
    )


@router.delete(
    "/{student_id}",
    response_model=ApiResponse[None],
    status_code=status.HTTP_200_OK,
)
def delete_student(
    student_id: str,
    service: StudentAppService = Depends(get_student_service),
    _: AuthenticatedUser = Depends(require_teacher),
) -> ApiResponse[None]:
    service.delete_student(student_id)
    return ApiResponse(success=True, data=None)
