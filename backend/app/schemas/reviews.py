from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from app.schemas.responses import ApiModel

ReviewSubject = Literal["math", "history"]
ReviewStatus = Literal["pending", "adjusted", "cancelled"]


class ReviewRequestCreate(ApiModel):
    subject: ReviewSubject
    justification: str = Field(min_length=10, max_length=2000)


class ReviewDecision(ApiModel):
    action: Literal["adjusted", "cancelled"]
    teacher_response: str = Field(min_length=1, max_length=2000)
    adjusted_grade: float | None = Field(default=None, ge=0, le=20)

    @model_validator(mode="after")
    def validate_grade_for_action(self) -> "ReviewDecision":
        if self.action == "adjusted" and self.adjusted_grade is None:
            raise ValueError("Informe a nova nota para concluir com ajuste.")
        if self.action == "cancelled" and self.adjusted_grade is not None:
            raise ValueError("Um pedido cancelado não pode alterar a nota.")
        return self


class ReviewRequestResponse(ApiModel):
    id: int
    student_id: str
    student_name: str
    student_email: str
    subject: ReviewSubject
    justification: str
    original_grade: float
    status: ReviewStatus
    teacher_response: str | None
    adjusted_grade: float | None
    created_at: datetime
    decided_at: datetime | None
