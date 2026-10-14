from typing import Literal

from pydantic import ConfigDict, EmailStr, Field

from app.schemas.responses import ApiModel


UserRole = Literal["student", "teacher"]
DemoProfile = Literal["professor", "aluno_1", "aluno_2"]


class LoginRequest(ApiModel):
    model_config = ConfigDict(extra="forbid")

    profile: DemoProfile = Field(
        default="professor",
        description=(
            "Perfil para autenticar. O servidor resolve a conta e a senha "
            "a partir da configuração privada do backend."
        ),
    )


class AuthenticatedUser(ApiModel):
    email: EmailStr
    role: UserRole
    student_id: str | None = None


class TokenPair(ApiModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: AuthenticatedUser


class RefreshRequest(ApiModel):
    refresh_token: str
