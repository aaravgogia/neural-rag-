from statistics import quantiles
from typing import Iterable

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.auth import get_current_user
from app.models.database import EvalMetric, User, get_db

router = APIRouter(prefix="/evals", tags=["Quality analytics"])

def summarize(records: Iterable[EvalMetric]) -> dict:
    items = list(records)
    latencies = sorted(float(item.latency_ms or 0) for item in items)
    percentile = lambda value: latencies[max(0, min(len(latencies) - 1, round((len(latencies) - 1) * value)))] if latencies else 0.0
    return {
        "total_queries": len(items),
        "avg_groundedness": round(sum(float(item.groundedness or 0) for item in items) / len(items), 3) if items else 0.0,
        "avg_retrieval_relevance": round(sum(float(item.retrieval_relevance or 0) for item in items) / len(items), 3) if items else 0.0,
        "cache_hit_rate": round(sum(1 for item in items if item.cache_hit) / len(items), 3) if items else 0.0,
        "p50_latency_ms": round(percentile(.5), 1),
        "p95_latency_ms": round(percentile(.95), 1),
        "trend": [{"timestamp": item.timestamp.isoformat(), "groundedness": item.groundedness, "retrieval_relevance": item.retrieval_relevance} for item in reversed(items)],
        "latency_distribution": [{"label": "<250ms", "count": sum(1 for value in latencies if value < 250)}, {"label": "250–500ms", "count": sum(1 for value in latencies if 250 <= value < 500)}, {"label": "500ms–1s", "count": sum(1 for value in latencies if 500 <= value < 1000)}, {"label": "1–2s", "count": sum(1 for value in latencies if 1000 <= value < 2000)}, {"label": ">2s", "count": sum(1 for value in latencies if value >= 2000)}],
    }

@router.get("/summary")
async def get_summary(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    records = (await db.execute(select(EvalMetric).where(EvalMetric.user_id == current_user.id).order_by(EvalMetric.timestamp.desc()))).scalars().all()
    return summarize(records)

@router.get("/recent")
async def get_recent(limit: int = Query(20, ge=1, le=100), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    records = (await db.execute(select(EvalMetric).where(EvalMetric.user_id == current_user.id).order_by(EvalMetric.timestamp.desc()).limit(limit))).scalars().all()
    return [{"session_id": item.session_id, "query_text": item.query_text, "groundedness": item.groundedness, "retrieval_relevance": item.retrieval_relevance, "latency_ms": item.latency_ms, "node_timings": item.node_timings, "timestamp": item.timestamp.isoformat(), "cache_hit": item.cache_hit} for item in records]
