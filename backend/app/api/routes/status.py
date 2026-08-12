"""Public, computation-backed operational health for the status page."""
import time

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.evals import summarize
from app.core.eval_metrics import rolling_metrics
from app.models.database import EvalMetric, get_db

router = APIRouter(tags=["Status"])


def build_status_payload(started_at: float, records, metrics_source: str) -> dict:
    summary = summarize(records)
    return {
        "status": "ok",
        "uptime_seconds": round(max(0, time.monotonic() - started_at), 1),
        "p50_latency_ms": summary["p50_latency_ms"],
        "p95_latency_ms": summary["p95_latency_ms"],
        "cache_hit_rate": summary["cache_hit_rate"],
        "samples": summary["total_queries"],
        "metrics_source": metrics_source,
    }


@router.get("/status")
async def get_status(request: Request, db: AsyncSession = Depends(get_db)):
    try:
        records = (await db.execute(select(EvalMetric).order_by(EvalMetric.timestamp.desc()).limit(1000))).scalars().all()
        return build_status_payload(request.app.state.started_at, records, "database")
    except Exception:
        # Availability telemetry must remain useful even when analytics storage is not.
        return build_status_payload(request.app.state.started_at, rolling_metrics(), "in_memory")
