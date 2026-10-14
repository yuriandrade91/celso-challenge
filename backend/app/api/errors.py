import logging
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.domain.exceptions import StudentAlreadyExistsError, StudentNotFoundError
from app.schemas.responses import ApiError, ApiResponse

logger = logging.getLogger(__name__)


def _camel_case(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


def _validation_field(location: tuple[Any, ...]) -> str | None:
    parts = [str(part) for part in location if part not in ("body", "query", "path")]
    if not parts:
        return None
    return ".".join(_camel_case(part) for part in parts)


def _http_error_code(status_code: int) -> str:
    try:
        return HTTPStatus(status_code).name
    except ValueError:
        return "HTTP_ERROR"


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StudentAlreadyExistsError)
    async def duplicate_student_handler(
        _request: Request, error: StudentAlreadyExistsError
    ) -> JSONResponse:
        response = ApiResponse[list[Any]](
            success=False,
            data=[],
            errors=[
                ApiError(
                    field=error.field,
                    code="BUSINESS_RULE_VIOLATION",
                    message=str(error),
                )
            ],
        )
        return JSONResponse(
            status_code=409,
            content=response.model_dump(by_alias=True, mode="json"),
        )

    @app.exception_handler(StudentNotFoundError)
    async def student_not_found_handler(
        _request: Request, error: StudentNotFoundError
    ) -> JSONResponse:
        response = ApiResponse[list[Any]](
            success=False,
            data=[],
            errors=[
                ApiError(
                    field=error.field,
                    code="NOT_FOUND",
                    message="Student not found.",
                )
            ],
        )
        return JSONResponse(
            status_code=404,
            content=response.model_dump(by_alias=True, mode="json"),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _request: Request, error: RequestValidationError
    ) -> JSONResponse:
        errors = [
            ApiError(
                field=_validation_field(tuple(issue["loc"])),
                code="VALIDATION_ERROR",
                message=str(issue["msg"]),
            )
            for issue in error.errors()
        ]
        response = ApiResponse[list[Any]](
            success=False,
            data=[],
            errors=errors,
        )
        return JSONResponse(
            status_code=422,
            content=response.model_dump(by_alias=True, mode="json"),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(
        _request: Request, error: StarletteHTTPException
    ) -> JSONResponse:
        message = (
            error.detail
            if isinstance(error.detail, str)
            else "A solicitação não pode ser concluída."
        )
        response = ApiResponse[list[Any]](
            success=False,
            data=[],
            errors=[
                ApiError(
                    field=None,
                    code=_http_error_code(error.status_code),
                    message=message,
                )
            ],
        )
        return JSONResponse(
            status_code=error.status_code,
            content=response.model_dump(by_alias=True, mode="json"),
            headers=error.headers,
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(
        request: Request, error: Exception
    ) -> JSONResponse:
        logger.exception(
            "Unhandled API error on %s %s",
            request.method,
            request.url.path,
            exc_info=error,
        )
        response = ApiResponse[list[Any]](
            success=False,
            data=[],
            errors=[
                ApiError(
                    field=None,
                    code="INTERNAL_SERVER_ERROR",
                    message="Ocorreu um erro interno ao processar a solicitação.",
                )
            ],
        )
        return JSONResponse(
            status_code=500,
            content=response.model_dump(by_alias=True, mode="json"),
        )
