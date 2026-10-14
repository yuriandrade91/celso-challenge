from datetime import datetime, timezone
from typing import Annotated, Generic, TypeVar

from pydantic import AfterValidator, BaseModel, ConfigDict

T = TypeVar("T")


def _assume_utc(value: datetime) -> datetime:
    """O SQLite devolve datas sem fuso; todas são gravadas em UTC."""
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


# Serializa com "Z" (UTC): sem fuso, o browser leria a data como hora local.
UtcDateTime = Annotated[datetime, AfterValidator(_assume_utc)]


def to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class ApiError(ApiModel):
    field: str | None
    code: str
    message: str


class Pagination(ApiModel):
    page_number: int
    page_size: int
    total_records: int
    total_pages: int
    has_next_page: bool
    has_previous_page: bool


class ApiResponse(ApiModel, Generic[T]):
    success: bool
    data: T
    pagination: Pagination | None = None
    errors: list[ApiError] | None = None
