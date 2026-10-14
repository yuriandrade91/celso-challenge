import json
import logging
import os
import sys
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

from app.metrics import RUNTIME_METRICS

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
execution_id_var: ContextVar[str | None] = ContextVar("execution_id", default=None)
trace_id_var: ContextVar[str | None] = ContextVar("trace_id", default=None)
span_id_var: ContextVar[str | None] = ContextVar("span_id", default=None)
_span_logger = logging.getLogger("app.tracing")

_RESERVED_ATTRIBUTES = set(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__
) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    """Uma linha JSON por evento, com IDs de correlação do contexto atual."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for name, value in (
            ("request_id", request_id_var.get()),
            ("execution_id", execution_id_var.get()),
            ("trace_id", trace_id_var.get()),
            ("span_id", span_id_var.get()),
        ):
            if value:
                payload[name] = value
        payload.update(
            (key, value)
            for key, value in record.__dict__.items()
            if key not in _RESERVED_ATTRIBUTES and not key.startswith("_")
        )
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging() -> None:
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)


def log_event(
    logger: logging.Logger, event: str, level: int = logging.INFO, **fields: Any
) -> None:
    """Regista um evento estruturado; os campos nunca devem conter PII em claro."""
    RUNTIME_METRICS.record_event(event)
    logger.log(level, event, extra={"event": event, **fields}, stacklevel=2)


@contextmanager
def span(
    name: str, level: int = logging.INFO, **attributes: Any
) -> Iterator[dict[str, Any]]:
    """Span simulado no modelo do OpenTelemetry, emitido como evento JSON.

    O trace herda o `request_id` (ou abre um novo); cada span conhece o pai pelo
    contexto, que o asyncio copia para tarefas e threads. Atributos extra podem
    ser adicionados ao dicionário devolvido durante o span.
    """
    trace_id = trace_id_var.get() or request_id_var.get() or uuid.uuid4().hex
    parent_span_id = span_id_var.get()
    span_id = uuid.uuid4().hex[:16]
    trace_token = trace_id_var.set(trace_id)
    span_token = span_id_var.set(span_id)
    started_at = time.perf_counter()
    status = "ok"
    error_type = None
    extra: dict[str, Any] = dict(attributes)
    try:
        yield extra
    except BaseException as error:
        status = "error"
        error_type = type(error).__name__
        raise
    finally:
        span_id_var.reset(span_token)
        trace_id_var.reset(trace_token)
        _span_logger.log(
            logging.WARNING if status == "error" and level < logging.WARNING else level,
            "span",
            extra={
                "event": "span",
                "span_name": name,
                "trace_id": trace_id,
                "span_id": span_id,
                "parent_span_id": parent_span_id,
                "status": status,
                "error_type": error_type,
                "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
                **extra,
            },
        )
