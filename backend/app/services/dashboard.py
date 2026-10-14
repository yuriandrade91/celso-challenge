from app.metrics import RUNTIME_METRICS
from app.repositories.reports import ReportRepository
from app.schemas.reports import CircuitState, Metrics, OperationalMetrics
from app.services.demo_metrics import demo_metrics_enabled
from app.services.providers import circuit_states

# Eventos estruturados (log_event) que viram contadores operacionais.
_EVENT_COUNTERS = {
    "llm_retries": "grade_report.provider.retry",
    "llm_fallbacks": "grade_report.summary.fallback",
    "llm_throttles": "llm.throttled",
    "prompts_truncados": "llm.prompt_truncated",
    "orcamentos_esgotados": "grade_report.budget.exhausted",
    "notificacoes_enviadas": "grade_report.notification.sent",
    "alunos_com_falha": "grade_report.student_failed",
    "pedidos_bloqueados_rate_limit": "security.rate_limited",
}


def operational_metrics() -> OperationalMetrics:
    snapshot = RUNTIME_METRICS.snapshot()
    events = snapshot.pop("events")
    circuits = circuit_states()
    return OperationalMetrics(
        **snapshot,
        **{field: events.get(event, 0) for field, event in _EVENT_COUNTERS.items()},
        circuito_llm=CircuitState(**circuits["llm"]),
        circuito_smtp=CircuitState(**circuits["smtp"]),
    )


def dashboard_metrics(repository: ReportRepository, recent_limit: int = 5) -> Metrics:
    """Uma única resposta com tudo o que o painel do professor mostra."""
    reports_sent, pending_reviews = repository.count_reports_and_pending_reviews()
    return Metrics(
        total_alunos_processados=reports_sent,
        revisoes_pendentes=pending_reviews,
        dispatcher=repository.summarize_executions(),
        operacional=operational_metrics(),
        ultimas_execucoes=repository.list_executions(recent_limit),
        dados_emulados=demo_metrics_enabled(),
    )
