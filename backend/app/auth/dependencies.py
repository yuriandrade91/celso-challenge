import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth.security import decode_access_token, get_auth_settings
from app.database import get_db
from app.models import UserModel
from app.schemas.auth import AuthenticatedUser

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> AuthenticatedUser:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="É necessário iniciar sessão.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorized
    try:
        email = decode_access_token(
            credentials.credentials, get_auth_settings().jwt_secret
        )
    except (jwt.InvalidTokenError, RuntimeError):
        raise unauthorized from None

    user = db.get(UserModel, email)
    if user is None:
        raise unauthorized
    return AuthenticatedUser(
        email=user.email, role=user.role, student_id=user.student_id
    )


def require_teacher(
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> AuthenticatedUser:
    if current_user.role != "teacher":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Esta operação está disponível apenas para professores.",
        )
    return current_user
