"""One-time migration from the configured Chroma collection to pgvector.

Run with VECTOR_STORE_PROVIDER=pgvector and a PostgreSQL DATABASE_URL after
the Alembic migration. The script copies stored vectors directly; it does not
call an embedding API or re-embed documents.
"""
import asyncio
import json
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import chromadb
from sqlalchemy import text

from app.config import settings
from app.models.database import AsyncSessionLocal
from app.core.vector_store import _pgvector_literal


async def main() -> None:
    if settings.VECTOR_STORE_PROVIDER.strip().lower() != "pgvector":
        raise RuntimeError("Set VECTOR_STORE_PROVIDER=pgvector before running this migration")
    if not settings.DATABASE_URL.startswith("postgresql"):
        raise RuntimeError("A PostgreSQL DATABASE_URL is required")
    collection = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR).get_collection(settings.CHROMA_COLLECTION_NAME)
    payload = collection.get(include=["documents", "metadatas", "embeddings"])
    rows = zip(payload["ids"], payload["documents"], payload["metadatas"], payload["embeddings"])
    statement = text(f"""INSERT INTO {settings.PGVECTOR_TABLE_NAME}
        (id, user_id, workspace_id, namespace, content, metadata, embedding)
        VALUES (:id, :user_id, :workspace_id, :namespace, :content,
                CAST(:metadata AS jsonb), CAST(:embedding AS vector))
        ON CONFLICT (id) DO UPDATE SET content = EXCLUDED.content,
          metadata = EXCLUDED.metadata, embedding = EXCLUDED.embedding""")
    migrated = skipped = 0
    async with AsyncSessionLocal() as session:
        for chroma_id, content, metadata, embedding in rows:
            metadata = metadata or {}
            workspace_id = metadata.get("workspace_id")
            if not workspace_id or embedding is None:
                skipped += 1
                continue
            await session.execute(statement, {"id": chroma_id or str(uuid.uuid4()), "user_id": metadata.get("user_id", "legacy"), "workspace_id": workspace_id, "namespace": metadata.get("namespace", "default"), "content": content, "metadata": json.dumps(metadata), "embedding": _pgvector_literal(embedding)})
            migrated += 1
        await session.commit()
    print(f"Migrated {migrated} Chroma embeddings to pgvector; skipped {skipped} unscoped rows.")


if __name__ == "__main__":
    asyncio.run(main())
