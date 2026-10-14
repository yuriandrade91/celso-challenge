import hashlib
import secrets
import time

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.auth.security import (
    encode_access_token,
    get_auth_settings,
    hash_password,
    verify_password,
)
from app.models import RefreshTokenModel, StudentModel, UserModel
from app.schemas.auth import AuthenticatedUser, DemoProfile, TokenPair
from app.services.seed import load_seed_students


class AuthenticationError(Exception):
    pass


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def bootstrap_accounts(db: Session) -> None:
    settings = get_auth_settings()
    try:
        teacher = db.get(UserModel, settings.teacher_email)
        if teacher is not None and teacher.role != "teacher":
            raise RuntimeError("O email configurado para professor já pertence a aluno.")
        if teacher is None:
            teacher = UserModel(
                email=settings.teacher_email,
                password_hash=hash_password(settings.teacher_password),
                role="teacher",
            )
            db.add(teacher)
        elif not verify_password(settings.teacher_password, teacher.password_hash):
            teacher.password_hash = hash_password(settings.teacher_password)

        students = db.scalars(select(StudentModel)).all()
        for student in students:
            email = student.email.strip().casefold()
            account = db.scalar(
                select(UserModel).where(
                    UserModel.student_id == student.student_id
                )
            )
            account_at_email = db.get(UserModel, email)
            if account is not None and account.role != "student":
                raise RuntimeError(
                    "A conta associada a um estudante da massa inicial tem "
                    "um perfil inválido."
                )
            if account is not None and account_at_email not in (None, account):
                raise RuntimeError(
                    "O email de um estudante da massa inicial já pertence a "
                    "outra conta."
                )
            if account is not None:
                if account.email != email:
                    db.execute(
                        delete(RefreshTokenModel).where(
                            RefreshTokenModel.user_email == account.email
                        )
                    )
                    account.email = email
                if not verify_password(
                    settings.student_password, account.password_hash
                ):
                    account.password_hash = hash_password(
                        settings.student_password
                    )
            elif account_at_email is not None:
                raise RuntimeError(
                    f"A conta {email} não pode ser associada ao estudante "
                    f"{student.student_id}."
                )
            else:
                db.add(
                    UserModel(
                        email=email,
                        password_hash=hash_password(settings.student_password),
                        role="student",
                        student_id=student.student_id,
                    )
                )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


class AuthService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_auth_settings()

    def login_demo_profile(self, profile: DemoProfile) -> TokenPair:
        if not self.settings.enable_swagger_demo_accounts:
            raise AuthenticationError(
                "A seleção de perfis de demonstração está desativada."
            )

        if profile == "professor":
            email = self.settings.teacher_email
            expected_password = self.settings.teacher_password
            expected_role = "teacher"
        else:
            student_index = 0 if profile == "aluno_1" else 1
            seed_students, _, _ = load_seed_students()
            if student_index >= len(seed_students):
                raise AuthenticationError(
                    "Não há dois estudantes disponíveis para autenticação."
                )
            seed_student = seed_students[student_index]
            email = str(seed_student.email).strip().casefold()
            student_exists = self.db.scalar(
                select(StudentModel.student_id).where(
                    StudentModel.email == email
                )
            )
            if student_exists is None:
                raise AuthenticationError(
                    "A massa de estudantes ainda não está sincronizada com o banco."
                )
            expected_password = self.settings.student_password
            expected_role = "student"

        user = self.db.get(UserModel, email)
        if (
            user is None
            or user.role != expected_role
            or not verify_password(expected_password, user.password_hash)
        ):
            raise AuthenticationError(
                "A conta selecionada não está configurada para autenticação."
            )
        return self._issue_tokens(user)

    def rotate_refresh_token(self, refresh_token: str) -> TokenPair:
        now = int(time.time())
        old_hash = _token_digest(refresh_token)
        result = self.db.execute(
            update(RefreshTokenModel)
            .where(
                RefreshTokenModel.token_hash == old_hash,
                RefreshTokenModel.revoked_at.is_(None),
                RefreshTokenModel.expires_at > now,
            )
            .values(revoked_at=now)
        )
        if result.rowcount != 1:
            self.db.rollback()
            raise AuthenticationError("Refresh token inválido ou expirado.")

        token_row = self.db.get(RefreshTokenModel, old_hash)
        user = (
            self.db.get(UserModel, token_row.user_email)
            if token_row is not None
            else None
        )
        if user is None:
            self.db.rollback()
            raise AuthenticationError("A conta associada ao token não existe.")
        return self._issue_tokens(user)

    def revoke_refresh_token(self, refresh_token: str) -> None:
        self.db.execute(
            update(RefreshTokenModel)
            .where(
                RefreshTokenModel.token_hash == _token_digest(refresh_token),
                RefreshTokenModel.revoked_at.is_(None),
            )
            .values(revoked_at=int(time.time()))
        )
        self.db.commit()

    def _issue_tokens(self, user: UserModel) -> TokenPair:
        now = int(time.time())
        expires_in = self.settings.access_token_minutes * 60
        refresh_token = secrets.token_urlsafe(48)
        self.db.add(
            RefreshTokenModel(
                token_hash=_token_digest(refresh_token),
                user_email=user.email,
                expires_at=now + self.settings.refresh_token_days * 24 * 60 * 60,
            )
        )
        access_token = encode_access_token(
            user.email,
            self.settings.jwt_secret,
            now + expires_in,
            now,
        )
        self.db.commit()
        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
            user=AuthenticatedUser(
                email=user.email,
                role=user.role,
                student_id=user.student_id,
            ),
        )
