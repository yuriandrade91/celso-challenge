import json
import logging

from fastapi.testclient import TestClient

from app.observability import JsonFormatter, execution_id_var, log_event


def test_json_formatter_adds_event_fields_and_correlation_ids(caplog) -> None:
    logger = logging.getLogger("tests.observability")
    caplog.set_level(logging.INFO, logger="tests.observability")
    token = execution_id_var.set("exec-123")
    try:
        log_event(logger, "grade_report.test", tokens=42)
        payload = json.loads(JsonFormatter().format(caplog.records[0]))
    finally:
        execution_id_var.reset(token)

    assert payload["event"] == "grade_report.test"
    assert payload["tokens"] == 42
    assert payload["execution_id"] == "exec-123"
    assert payload["level"] == "INFO"
    assert "ts" in payload


def test_request_id_is_propagated_or_generated() -> None:
    from app.main import app

    # Sem `with`: o lifespan (que inicializa o banco real) não é executado.
    client = TestClient(app)
    echoed = client.get("/openapi.json", headers={"X-Request-ID": "abc-123"})
    generated = client.get(
        "/openapi.json", headers={"X-Request-ID": "bad id value"}
    )

    assert echoed.headers["X-Request-ID"] == "abc-123"
    assert generated.headers["X-Request-ID"] not in ("", "bad id value")


def test_spans_form_a_trace_with_parent_child_links(caplog) -> None:
    from app.observability import request_id_var, span

    caplog.set_level(logging.DEBUG, logger="app.tracing")
    token = request_id_var.set("req-42")
    try:
        with span("parent"):
            with span("child", level=logging.DEBUG, kind="db"):
                pass
    finally:
        request_id_var.reset(token)

    spans = {
        event["span_name"]: event
        for event in (
            json.loads(JsonFormatter().format(record)) for record in caplog.records
        )
    }
    assert spans["child"]["parent_span_id"] == spans["parent"]["span_id"]
    assert spans["parent"]["parent_span_id"] is None
    assert spans["child"]["trace_id"] == spans["parent"]["trace_id"] == "req-42"
    assert spans["child"]["kind"] == "db"
    assert spans["child"]["level"] == "DEBUG"
    assert spans["parent"]["status"] == "ok"


def test_failed_span_is_marked_as_error(caplog) -> None:
    import pytest

    from app.observability import span

    caplog.set_level(logging.INFO, logger="app.tracing")
    with pytest.raises(ValueError):
        with span("broken"):
            raise ValueError("boom")

    event = json.loads(JsonFormatter().format(caplog.records[-1]))
    assert event["status"] == "error"
    assert event["error_type"] == "ValueError"
    assert event["level"] == "WARNING"


def test_pipeline_emits_nested_spans_per_student(caplog) -> None:
    import asyncio

    from app.services.reports import process_csv
    from tests.test_business import (
        FakeNotifier,
        FakeSummarizer,
        MemoryReportRepository,
        _csv,
    )

    caplog.set_level(logging.DEBUG, logger="app.tracing")
    asyncio.run(
        process_csv(
            _csv(
                "7f3c2a10-4b8e-4e21-9d55-0c6a1b2e9f01,Maria,maria@example.com,17,14"
            ),
            MemoryReportRepository(),
            FakeNotifier(),
            FakeSummarizer(),
        )
    )

    events = [json.loads(JsonFormatter().format(r)) for r in caplog.records]
    by_name = {event["span_name"]: event for event in events}
    execution, student = by_name["grade_report.execution"], by_name["grade_report.student"]
    assert student["parent_span_id"] == execution["span_id"]
    assert by_name["db.claim_report"]["parent_span_id"] == student["span_id"]
    assert student["outcome"] == "sent"
    assert {event["trace_id"] for event in events} == {execution["trace_id"]}


def test_runtime_metrics_count_events_and_http_latency() -> None:
    from app.metrics import RuntimeMetrics

    metrics = RuntimeMetrics()
    for duration in (10, 20, 30, 40, 100):
        metrics.record_http(200, duration)
    metrics.record_http(503, 5)
    metrics.record_http(429, 1)
    metrics.record_event("grade_report.provider.retry")
    metrics.record_event("grade_report.provider.retry")

    snapshot = metrics.snapshot()

    assert snapshot["http_requisicoes"] == 7
    assert snapshot["http_erros_5xx"] == 1
    assert snapshot["http_erros_4xx"] == 1
    assert snapshot["http_taxa_erro_5xx"] == round(1 / 7, 4)
    assert snapshot["http_latencia_p50_ms"] == 20
    assert snapshot["http_latencia_p95_ms"] == 100
    assert snapshot["events"]["grade_report.provider.retry"] == 2


def test_operational_metrics_report_open_circuit(monkeypatch) -> None:
    from app.services import providers
    from app.services.dashboard import operational_metrics

    breaker = providers._CircuitBreaker(failure_threshold=1)
    breaker.record_failure()
    monkeypatch.setattr(providers, "_OPENAI_CIRCUIT", breaker)

    metrics = operational_metrics()

    assert metrics.circuito_llm.estado == "open"
    assert metrics.circuito_llm.falhas_consecutivas == 1
    assert metrics.circuito_smtp.estado == "closed"
