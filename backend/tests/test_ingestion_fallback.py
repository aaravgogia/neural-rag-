import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app.core.ingestion as ingestion


@pytest.mark.asyncio
async def test_no_worker_deployment_ingests_inline(monkeypatch):
    """Free deployments must never leave a job queued with no ARQ worker."""
    calls = []

    async def fake_ingest(context, document_id):
        calls.append((context, document_id))

    monkeypatch.setattr(ingestion.settings, "INGESTION_QUEUE_ENABLED", False)
    monkeypatch.setattr(ingestion, "ingest_document", fake_ingest)

    result = await ingestion.enqueue_ingestion("document-free-tier")

    assert result == "inline"
    assert calls == [({}, "document-free-tier")]
