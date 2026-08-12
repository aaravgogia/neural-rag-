import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.api.routes.status import build_status_payload
from app.models.database import EvalMetric


def test_status_payload_uses_real_eval_metrics():
    records = [
        EvalMetric(session_id="a", query_text="a", latency_ms=100, cache_hit=False, timestamp=datetime.utcnow()),
        EvalMetric(session_id="b", query_text="b", latency_ms=300, cache_hit=True, timestamp=datetime.utcnow()),
        EvalMetric(session_id="c", query_text="c", latency_ms=900, cache_hit=True, timestamp=datetime.utcnow()),
    ]
    result = build_status_payload(time.monotonic() - 5, records, "database")
    assert result["status"] == "ok"
    assert result["p50_latency_ms"] == 300
    assert result["p95_latency_ms"] == 900
    assert result["cache_hit_rate"] == round(2 / 3, 3)
    assert result["samples"] == 3
    assert result["uptime_seconds"] >= 5
