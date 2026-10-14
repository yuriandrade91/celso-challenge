from uuid import UUID, uuid4

from pydantic import EmailStr, Field, field_validator, model_validator

from app.schemas.responses import ApiModel


class StudentCreate(ApiModel):
    student_id: str = Field(
        default_factory=lambda: str(uuid4()),
        json_schema_extra={"format": "uuid"},
    )
    name: str = Field(min_length=1)
    email: EmailStr
    math_grade: float = Field(ge=0, le=20)
    history_grade: float = Field(ge=0, le=20)

    @field_validator("student_id")
    @classmethod
    def student_id_must_be_uuid(cls, value: str) -> str:
        try:
            return str(UUID(value))
        except ValueError as error:
            raise ValueError("O ID do estudante deve ser um UUID válido.") from error


class StudentUpdate(ApiModel):
    math_grade: float | None = Field(default=None, ge=0, le=20)
    history_grade: float | None = Field(default=None, ge=0, le=20)
    review_requested: bool | None = None

    @model_validator(mode="after")
    def reject_explicit_nulls(self) -> "StudentUpdate":
        if any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("Campos enviados para atualização não podem ser nulos.")
        return self


class StudentResponse(StudentCreate):
    review_requested: bool
