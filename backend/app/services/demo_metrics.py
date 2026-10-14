"""Métricas emuladas para demonstração (ENABLE_DEMO_METRICS=true).

Sem uploads reais o painel de métricas fica a zero. Com a flag ligada, o
arranque grava um histórico fictício de execuções (execution_id `demo-*`,
provedores `demo`) e semeia os contadores operacionais do processo. Os dados
reais somam-se aos emulados; ao desligar a flag, o histórico `demo-*` é
apagado. A API devolve `dadosEmulados` para o painel sinalizar a origem.
"""

import math
import os
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, exists, select
from sqlalchemy.orm import Session

from app.metrics import RUNTIME_METRICS
from app.models import GradeReportExecutionModel

DEMO_PREFIX = "demo-"
DEMO_PROVIDER = "demo"
_CONCURRENCY = 5
# Resumo típico: ~210 tokens de prompt e ~125 de resposta por aluno.
_PROMPT_TOKENS = 210
_COMPLETION_TOKENS = 125
_USD_PER_STUDENT = (_PROMPT_TOKENS * 0.00015 + _COMPLETION_TOKENS * 0.0006) / 1000


def demo_metrics_enabled() -> bool:
    return os.getenv("ENABLE_DEMO_METRICS", "false").strip().lower() in {
        "1",
        "true",
        "yes",
    }


@dataclass(frozen=True)
class _DemoExecution:
    hours_ago: float
    processados: int
    ignorados_cache: int = 0
    duplicados: int = 0
    falhas_validacao: int = 0
    falhas_processamento: int = 0
    fallbacks: int = 0
    media_ms: float = 0
    p95_ms: float = 0
    orcamento_excedido: bool = False
    erro: str | None = None


# Uma quinzena plausível: primeira carga, reenvio em cache, correções de
# notas, uma indisponibilidade do LLM (fallbacks), teto de custo e uma falha
# de configuração.
_HISTORY = (
    _DemoExecution(318, 38, 0, 1, 2, 1, 2, 1180, 2140),
    _DemoExecution(266, 3, 36, 1, 2, 0, 0, 940, 1320),
    _DemoExecution(214, 112, 0, 2, 4, 2, 6, 1260, 2480),
    _DemoExecution(
        190, 0, erro="Configuração do servidor inválida: OPENAI_API_KEY ausente."
    ),
    _DemoExecution(142, 18, 98, 0, 3, 1, 1, 1090, 1710),
    _DemoExecution(95, 59, 0, 1, 3, 1, 9, 1420, 3050),
    _DemoExecution(46, 236, 0, 3, 6, 5, 4, 1210, 2390, orcamento_excedido=True),
    _DemoExecution(3, 10, 0, 3, 5, 0, 0, 1010, 1530),
)


def _execution_row(index: int, spec: _DemoExecution, now: datetime) -> GradeReportExecutionModel:
    attempted = spec.processados + spec.falhas_processamento
    summarized = spec.processados - spec.fallbacks
    total_linhas = (
        attempted + spec.ignorados_cache + spec.duplicados + spec.falhas_validacao
    )
    return GradeReportExecutionModel(
        execution_id=f"{DEMO_PREFIX}{index:04d}",
        created_at=now - timedelta(hours=spec.hours_ago),
        status="failed" if spec.erro else "completed",
        erro=spec.erro,
        total_linhas=total_linhas,
        processados=spec.processados,
        falhas=spec.falhas_validacao + spec.falhas_processamento,
        falhas_validacao=spec.falhas_validacao,
        falhas_processamento=spec.falhas_processamento,
        duplicados_ignorados=spec.duplicados,
        ignorados_cache=spec.ignorados_cache,
        fallbacks_llm=spec.fallbacks,
        orcamento_excedido=spec.orcamento_excedido,
        tokens_gastos=summarized * (_PROMPT_TOKENS + _COMPLETION_TOKENS),
        custo_estimado_usd=round(summarized * _USD_PER_STUDENT, 6),
        tempo_medio_processamento_ms=spec.media_ms,
        tempo_p95_processamento_ms=spec.p95_ms,
        tempo_total_ms=round(math.ceil(attempted / _CONCURRENCY) * spec.media_ms + 35, 1),
        summary_provider=DEMO_PROVIDER,
        notification_provider=DEMO_PROVIDER,
    )


def sync_demo_executions(db: Session) -> None:
    """Grava o histórico emulado uma vez; remove-o se a flag estiver desligada."""
    is_demo = GradeReportExecutionModel.execution_id.startswith(DEMO_PREFIX)
    if not demo_metrics_enabled():
        db.execute(delete(GradeReportExecutionModel).where(is_demo))
        db.commit()
        return
    if db.scalar(select(exists().where(is_demo))):
        return
    now = datetime.now(timezone.utc)
    db.add_all(_execution_row(index, spec, now) for index, spec in enumerate(_HISTORY, 1))
    db.commit()


def seed_demo_runtime_metrics() -> None:
    """Base emulada para os contadores do processo (zerados a cada arranque)."""
    if not demo_metrics_enabled():
        return
    rng = random.Random(2026)
    for status, count in ((200, 452), (404, 17), (422, 7), (502, 4)):
        for _ in range(count):
            # Latência log-normal: p50 ~38 ms, p95 ~130 ms.
            RUNTIME_METRICS.record_http(status, rng.lognormvariate(math.log(38), 0.75))
    for event, count in (
        ("grade_report.provider.retry", 6),
        ("grade_report.summary.fallback", 4),
        ("llm.throttled", 2),
        ("llm.prompt_truncated", 1),
        ("grade_report.notification.sent", 184),
        ("grade_report.student_failed", 3),
        ("security.rate_limited", 5),
    ):
        for _ in range(count):
            RUNTIME_METRICS.record_event(event)
