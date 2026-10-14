import math
import threading
from collections import Counter, deque
from datetime import datetime, timezone
from typing import Any

_LATENCY_WINDOW = 1000


def percentile(values: list[float], pct: float) -> float:
    """Percentil pelo método nearest-rank."""
    if not values:
        return 0
    ordered = sorted(values)
    rank = math.ceil(pct / 100 * len(ordered))
    return ordered[max(rank, 1) - 1]


class RuntimeMetrics:
    """Métricas operacionais do processo (contadores e janela de latência).

    Complementa as métricas persistidas por execução: aqui ficam sinais
    voláteis, como erros HTTP, retries e throttling, desde o arranque.
    Com várias réplicas, cada uma tem os seus valores (ver README).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self.started_at = datetime.now(timezone.utc)
            self._events: Counter[str] = Counter()
            self._status_classes: Counter[str] = Counter()
            self._latencies_ms: deque[float] = deque(maxlen=_LATENCY_WINDOW)

    def record_event(self, event: str) -> None:
        with self._lock:
            self._events[event] += 1

    def record_http(self, status_code: int, duration_ms: float) -> None:
        with self._lock:
            self._status_classes[f"{status_code // 100}xx"] += 1
            self._latencies_ms.append(duration_ms)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            events = dict(self._events)
            statuses = dict(self._status_classes)
            latencies = list(self._latencies_ms)
            started_at = self.started_at
        total = sum(statuses.values())
        errors = statuses.get("5xx", 0)
        return {
            "desde": started_at,
            "http_requisicoes": total,
            "http_erros_4xx": statuses.get("4xx", 0),
            "http_erros_5xx": errors,
            "http_taxa_erro_5xx": round(errors / total, 4) if total else 0,
            "http_latencia_p50_ms": round(percentile(latencies, 50), 2),
            "http_latencia_p95_ms": round(percentile(latencies, 95), 2),
            "events": events,
        }


RUNTIME_METRICS = RuntimeMetrics()
