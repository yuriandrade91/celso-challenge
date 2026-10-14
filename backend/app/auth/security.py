import base64
import hashlib
import hmac
import os
from dataclasses import dataclass

import jwt
from pydantic import EmailStr, TypeAdapter, ValidationError


PASSWORD_HASH_ITERATIONS = 310_000
JWT_ALGORITHM = "HS256"


@dataclass(frozen=True)
class AuthSettings:
    jwt_secret: str
    teacher_email: str
    teacher_password: str
    student_password: str
    access_token_minutes: int
    refresh_token_days: int
    enable_swagger_demo_accounts: bool


def get_auth_settings() -> AuthSettings:
    jwt_secret = os.getenv("JWT_SECRET_KEY", "")
    teacher_email = os.getenv("BOOTSTRAP_TEACHER_EMAIL", "").strip().casefold()
    teacher_password = os.getenv("BOOTSTRAP_TEACHER_PASSWORD", "")
    student_password = os.getenv("BOOTSTRAP_STUDENT_PASSWORD", "")
    if not jwt_secret:
        raise RuntimeError(
            "JWT_SECRET_KEY não foi definido. Crie backend/.env a partir de "
            ".env.example e configure as variáveis de autenticação."
        )
    if len(jwt_secret) < 32 or "replace" in jwt_secret.lower():
        raise RuntimeError(
            "JWT_SECRET_KEY precisa ter pelo menos 32 caracteres aleatórios "
            "e não pode ser um valor de exemplo."
        )
    if any(
        value.lower().startswith(marker)
        for value in (teacher_password, student_password)
        for marker in ("change-this", "replace-with")
    ):
        raise RuntimeError(
            "Substitua as palavras-passe de exemplo por valores privados."
        )
    if not teacher_email or len(teacher_password) < 12:
        raise RuntimeError(
            "Configure BOOTSTRAP_TEACHER_EMAIL e uma "
            "BOOTSTRAP_TEACHER_PASSWORD com pelo menos 12 caracteres."
        )
    if len(student_password) < 12:
        raise RuntimeError(
            "Configure BOOTSTRAP_STUDENT_PASSWORD com pelo menos 12 caracteres."
        )
    try:
        TypeAdapter(EmailStr).validate_python(teacher_email)
    except ValidationError as error:
        raise RuntimeError("BOOTSTRAP_TEACHER_EMAIL deve ser um email válido.") from error

    access_minutes = int(os.getenv("ACCESS_TOKEN_MINUTES", "15"))
    refresh_days = int(os.getenv("REFRESH_TOKEN_DAYS", "7"))
    if access_minutes < 1 or refresh_days < 1:
        raise RuntimeError("Os períodos de validade dos tokens devem ser positivos.")
    demo_accounts_value = os.getenv("ENABLE_SWAGGER_DEMO_ACCOUNTS", "false").lower()
    if demo_accounts_value not in {"true", "false"}:
        raise RuntimeError("ENABLE_SWAGGER_DEMO_ACCOUNTS deve ser true ou false.")
    return AuthSettings(
        jwt_secret=jwt_secret,
        teacher_email=teacher_email,
        teacher_password=teacher_password,
        student_password=student_password,
        access_token_minutes=access_minutes,
        refresh_token_days=refresh_days,
        enable_swagger_demo_accounts=demo_accounts_value == "true",
    )


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PASSWORD_HASH_ITERATIONS
    )
    return "$".join(
        (
            str(PASSWORD_HASH_ITERATIONS),
            base64.urlsafe_b64encode(salt).decode("ascii"),
            base64.urlsafe_b64encode(digest).decode("ascii"),
        )
    )


def verify_password(password: str, password_hash: str) -> bool:
    try:
        iterations, salt_text, digest_text = password_hash.split("$", maxsplit=2)
        salt = base64.urlsafe_b64decode(salt_text.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_text.encode("ascii"))
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, int(iterations)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def encode_access_token(
    email: str, secret: str, expires_at: int, issued_at: int
) -> str:
    return jwt.encode(
        {
            "sub": email,
            "type": "access",
            "iat": issued_at,
            "exp": expires_at,
        },
        secret,
        algorithm=JWT_ALGORITHM,
    )


def decode_access_token(token: str, secret: str) -> str:
    payload = jwt.decode(token, secret, algorithms=[JWT_ALGORITHM])
    if payload.get("type") != "access" or not isinstance(payload.get("sub"), str):
        raise jwt.InvalidTokenError("Token de acesso inválido.")
    return payload["sub"]
