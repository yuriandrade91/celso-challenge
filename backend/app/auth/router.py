from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.auth.service import AuthService, AuthenticationError
from app.database import get_db
from app.rate_limit import limit_login
from app.schemas.auth import (
    AuthenticatedUser,
    LoginRequest,
    RefreshRequest,
    TokenPair,
)
from app.schemas.responses import ApiResponse

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.get("/me", response_model=ApiResponse[AuthenticatedUser])
def get_authenticated_user(
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> ApiResponse[AuthenticatedUser]:
    return ApiResponse(success=True, data=current_user)


@router.post(
    "/login",
    response_model=ApiResponse[TokenPair],
    dependencies=[Depends(limit_login)],
)
def login(
    credentials: LoginRequest = Body(
        openapi_examples={
            "professor": {
                "summary": "Professor (padrão)",
                "value": {"profile": "professor"},
            },
            "aluno_1": {
                "summary": "Aluno 1",
                "value": {"profile": "aluno_1"},
            },
            "aluno_2": {
                "summary": "Aluno 2",
                "value": {"profile": "aluno_2"},
            },
        }
    ),
    db: Session = Depends(get_db),
) -> ApiResponse[TokenPair]:
    try:
        tokens = AuthService(db).login_demo_profile(credentials.profile)
    except AuthenticationError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error)
        ) from error
    return ApiResponse(success=True, data=tokens)


@router.post(
    "/refresh",
    response_model=ApiResponse[TokenPair],
    dependencies=[Depends(limit_login)],
)
def refresh(
    request: RefreshRequest, db: Session = Depends(get_db)
) -> ApiResponse[TokenPair]:
    try:
        tokens = AuthService(db).rotate_refresh_token(request.refresh_token)
    except AuthenticationError as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error)) from error
    return ApiResponse(success=True, data=tokens)


@router.post("/logout", response_model=ApiResponse[None])
def logout(
    request: RefreshRequest, db: Session = Depends(get_db)
) -> ApiResponse[None]:
    AuthService(db).revoke_refresh_token(request.refresh_token)
    return ApiResponse(success=True, data=None)
