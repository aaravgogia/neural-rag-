"""Live pgvector add/query/delete smoke check.

Requires a PostgreSQL pgvector database, VECTOR_STORE_PROVIDER=pgvector, and
an OpenAI embedding key. It does not touch production document namespaces.
"""
import asyncio
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from langchain_core.documents import Document

from app.config import settings
from app.core.vector_store import VectorStoreManager
from app.models.database import init_db


async def main() -> None:
    if settings.VECTOR_STORE_PROVIDER.strip().lower() != "pgvector":
        raise RuntimeError("Set VECTOR_STORE_PROVIDER=pgvector")
    if not settings.OPENAI_API_KEY:
        raise RuntimeError("Set OPENAI_API_KEY for the configured OpenAI embedding backend")

    await init_db()
    store = VectorStoreManager()
    workspace = f"pgvector-smoke-{uuid.uuid4()}"
    ids = await store.add_documents(
        [Document(page_content="The pgvector smoke test retrieval phrase is orbital mango.")],
        user_id="pgvector-smoke", workspace_id=workspace, namespace="smoke",
    )
    try:
        matches = await store.similarity_search("orbital mango", "pgvector-smoke", workspace, namespace="smoke", score_threshold=0)
        if not matches or "orbital mango" not in matches[0][0].page_content:
            raise RuntimeError("pgvector retrieval did not return the inserted document")
        print("pgvector smoke check passed")
    finally:
        await store.delete_documents(ids)


if __name__ == "__main__":
    asyncio.run(main())
