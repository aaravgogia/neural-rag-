"""Persistence for product-quality signals produced by the observable agent."""
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.models.database import AsyncSessionLocal, EvalMetric

logger = logging.getLogger(__name__)
_rolling_metrics = deque(maxlen=1000)


@dataclass
class RollingMetric:
    latency_ms: float
    cache_hit: bool
    groundedness: float = 0.0
    retrieval_relevance: float = 0.0
    timestamp: datetime = field(default_factory=datetime.utcnow)


def rolling_metrics() -> list[RollingMetric]:
    """Process-local telemetry keeps /status useful during a DB outage."""
    return list(_rolling_metrics)

async def persist_eval_metric(record: dict[str, Any]) -> None:
    _rolling_metrics.append(RollingMetric(
        latency_ms=float(record.get("latency_ms", 0)), cache_hit=bool(record.get("cache_hit", False)),
        groundedness=float(record.get("groundedness", 0)), retrieval_relevance=float(record.get("retrieval_relevance", 0)),
    ))
    try:
        async with AsyncSessionLocal() as session:
            session.add(EvalMetric(**record))
            await session.commit()
    except Exception:
        # Analytics should never make an answer fail; errors remain observable.
        logger.exception("Could not persist evaluation metric")
