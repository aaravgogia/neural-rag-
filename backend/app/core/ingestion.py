"""Durable ARQ ingestion with a best-effort local fallback."""
import asyncio, logging, os
from sqlalchemy import select
from app.config import settings
from app.core.document_processor import DocumentProcessor
from app.models.database import AsyncSessionLocal, Document, DocumentChunk, DocumentRedaction

logger = logging.getLogger(__name__)

async def ingest_document(ctx, document_id: str):
    """Worker entrypoint; only chunks absent from the parent version are embedded."""
    async with AsyncSessionLocal() as db:
        document = (await db.execute(select(Document).where(Document.id == document_id))).scalar_one_or_none()
        if not document: return
        document.status, document.ingestion_progress, document.ingestion_error = "processing", 10, None
        await db.commit()
        try:
            processor = DocumentProcessor()
            chunks = await processor.process_document(document.stored_path, metadata={"source": document.filename, "doc_title": document.filename, "namespace": document.namespace, "user_id": document.user_id, "workspace_id": document.workspace_id, "document_id": document.id})
            for chunk_index, chunk in enumerate(chunks):
                # PyPDFLoader exposes zero-based `page`; citations are a
                # human-facing 1-based page number. Other loaders simply omit it.
                page = chunk.metadata.get("page")
                source_page = int(page) + 1 if isinstance(page, int) else None
                chunk.metadata["source_page"] = source_page
                chunk.metadata["chunk_index"] = chunk_index
            prior = {}
            if document.parent_document_id:
                rows = (await db.execute(select(DocumentChunk).where(DocumentChunk.document_id == document.parent_document_id))).scalars().all()
                prior = {row.chunk_hash: row.vector_id for row in rows if row.vector_id}
            changed = [chunk for chunk in chunks if chunk.metadata["chunk_hash"] not in prior]
            document.ingestion_progress = 50; await db.commit()
            vector_ids = []
            if changed:
                # Keep route and worker-module imports lightweight.  The production
                # vector-store dependencies are only needed when a changed chunk is
                # actually ready to be embedded.
                from app.core.vector_store import VectorStoreManager
                store = VectorStoreManager()
                vector_ids = await store.add_documents(changed, user_id=document.user_id, workspace_id=document.workspace_id, namespace=document.namespace)
            by_hash = {chunk.metadata["chunk_hash"]: vector_id for chunk, vector_id in zip(changed, vector_ids)}
            all_ids = [by_hash.get(chunk.metadata["chunk_hash"], prior.get(chunk.metadata["chunk_hash"])) for chunk in chunks]
            db.add_all([DocumentChunk(document_id=document.id, chunk_hash=chunk.metadata["chunk_hash"], vector_id=vector_id, source_page=chunk.metadata.get("source_page"), chunk_index=chunk.metadata.get("chunk_index")) for chunk, vector_id in zip(chunks, all_ids)])
            db.add_all([DocumentRedaction(document_id=document.id, user_id=document.user_id, entity_type=match.entity_type, replacement=match.replacement, original_value=match.original_value, source_page=page) for match, page in processor.last_redactions])
            document.vector_ids, document.chunks_count, document.status, document.ingestion_progress = [item for item in all_ids if item], len(chunks), "done", 100
            await db.commit()
        except Exception as error:
            logger.exception("Document ingestion failed")
            document.status, document.ingestion_error = "failed", str(error)[:500]
            await db.commit()
        finally:
            # Retain the generated upload path: authorized citation viewers
            # need the original file after background ingestion completes.
            pass

async def enqueue_ingestion(document_id: str):
    if not settings.INGESTION_QUEUE_ENABLED:
        # $0 / single-service deployments intentionally have no ARQ worker.
        # Run to completion in this request process rather than enqueueing a
        # job that no process will ever consume.
        logger.info("ARQ worker disabled; ingesting document %s inline", document_id)
        await ingest_document({}, document_id)
        return "inline"
    if settings.INGESTION_QUEUE_ENABLED:
        try:
            from arq import create_pool
            from arq.connections import RedisSettings
            pool = await create_pool(RedisSettings.from_dsn(settings.REDIS_URL))
            await pool.enqueue_job("ingest_document", document_id)
            await pool.aclose(); return "arq"
        except Exception as error:
            logger.warning("ARQ unavailable; using in-process ingestion fallback: %s", error)
    # Redis was unavailable, so schedule work in this same process.  This is
    # intentionally non-blocking for deployments that did configure a worker
    # but experience a short Redis outage.
    asyncio.create_task(ingest_document({}, document_id)); return "in_process"

try:
    from arq.connections import RedisSettings
    class WorkerSettings:
        functions = [ingest_document]
        redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
except ImportError:  # keeps local/demo imports alive until full deps are installed
    class WorkerSettings:
        functions = [ingest_document]
        redis_settings = None
