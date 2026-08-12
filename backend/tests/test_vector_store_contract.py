"""Shared storage-contract tests for vector store backends.

The production pgvector integration is exercised against Postgres in deployment
CI. These unit tests deliberately mock the database and embedding client so
they enforce the same public add/query/delete/retriever contract locally.
"""
import pytest
from langchain_core.documents import Document

from app.core.vector_store import PgvectorVectorStore, VectorStoreManager
import app.core.vector_store as vector_store_module


class FakeEmbeddings:
    def embed_documents(self, texts):
        return [[0.1, 0.2, 0.3] for _ in texts]

    def embed_query(self, text):
        return [0.1, 0.2, 0.3]


class FakeResult:
    def __init__(self, rows=()):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class FakeSession:
    def __init__(self, rows=()):
        self.rows = rows
        self.calls = []
        self.committed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def execute(self, statement, params):
        self.calls.append((str(statement), params))
        return FakeResult(self.rows)

    async def commit(self):
        self.committed = True


def pg_store():
    store = object.__new__(PgvectorVectorStore)
    store.embeddings = FakeEmbeddings()
    store.table = "vector_embeddings"
    return store


@pytest.mark.asyncio
async def test_pgvector_add_query_delete_and_retriever_share_vector_store_contract(monkeypatch):
    """The pgvector implementation returns IDs, filters scope, and deletes IDs."""
    session = FakeSession(rows=[{
        "id": "chunk-1", "content": "Refunds are available for thirty days.",
        "metadata": {"source": "policy.pdf", "workspace_id": "workspace-a"}, "score": 0.91,
    }])
    monkeypatch.setattr(vector_store_module, "AsyncSessionLocal", lambda: session)
    store = pg_store()

    ids = await store.add_documents([Document(page_content="Refunds are available for thirty days.", metadata={"source": "policy.pdf"})], "user-a", "workspace-a", "hr")
    assert len(ids) == 1
    assert session.committed
    insert_sql, insert_params = session.calls[0]
    assert "INSERT INTO vector_embeddings" in insert_sql
    assert insert_params["workspace_id"] == "workspace-a"
    assert insert_params["namespace"] == "hr"

    matches = await store.similarity_search("refund policy", "user-b", "workspace-a", k=3, namespace="hr", score_threshold=.7)
    assert [(doc.page_content, score) for doc, score in matches] == [("Refunds are available for thirty days.", .91)]
    query_sql, query_params = session.calls[1]
    assert "workspace_id = :workspace_id" in query_sql
    assert "namespace = :namespace" in query_sql
    assert query_params["workspace_id"] == "workspace-a"
    assert query_params["namespace"] == "hr"

    retriever = store.get_retriever("user-a", "workspace-a", k=1, namespace="hr")
    documents = await retriever.ainvoke("refund policy")
    assert documents[0].page_content == "Refunds are available for thirty days."

    assert await store.delete_documents(ids)
    delete_sql, delete_params = session.calls[-1]
    assert "DELETE FROM vector_embeddings" in delete_sql
    assert delete_params["ids"] == ids


@pytest.mark.asyncio
async def test_pgvector_query_does_not_cross_workspace_boundaries(monkeypatch):
    session = FakeSession()
    monkeypatch.setattr(vector_store_module, "AsyncSessionLocal", lambda: session)
    await pg_store().similarity_search("policy", "user-a", "workspace-only", namespace=None)
    _, params = session.calls[0]
    assert params["workspace_id"] == "workspace-only"
    assert "namespace" not in params


@pytest.mark.parametrize("provider, backend_name", [("chroma", "ChromaVectorStore"), ("pgvector", "PgvectorVectorStore")])
def test_manager_selects_each_provider_behind_the_same_contract(monkeypatch, provider, backend_name):
    """Both configuration values expose the identical manager API."""
    class Backend:
        async def add_documents(self, *args, **kwargs): return ["id"]
        async def similarity_search(self, *args, **kwargs): return []
        async def delete_documents(self, *args, **kwargs): return True
        def get_retriever(self, *args, **kwargs): return object()

    monkeypatch.setattr(vector_store_module.settings, "VECTOR_STORE_PROVIDER", provider)
    monkeypatch.setattr(vector_store_module, backend_name, Backend)
    store = VectorStoreManager()
    assert isinstance(store.backend, Backend)
    for method in ("add_documents", "similarity_search", "delete_documents", "get_retriever"):
        assert callable(getattr(store, method))


def test_pgvector_supports_sentence_transformer_embeddings_for_free_neon_stack(monkeypatch):
    monkeypatch.setattr(vector_store_module.settings, "DATABASE_URL", "postgresql+asyncpg://test")
    monkeypatch.setattr(vector_store_module.settings, "EMBEDDING_PROVIDER", "sentence_transformers")
    sentinel = object()
    monkeypatch.setattr(vector_store_module, "create_embedding_function", lambda: sentinel)
    assert PgvectorVectorStore().embeddings is sentinel


def test_pgvector_supports_lightweight_hashing_embeddings_for_render_free(monkeypatch):
    monkeypatch.setattr(vector_store_module.settings, "DATABASE_URL", "postgresql+asyncpg://test")
    monkeypatch.setattr(vector_store_module.settings, "EMBEDDING_PROVIDER", "hashing")
    monkeypatch.setattr(vector_store_module.settings, "PGVECTOR_DIMENSIONS", 384)
    store = PgvectorVectorStore()

    vector = store.embeddings.embed_query("invoice 4471")
    assert len(vector) == 384
    assert any(vector)


def test_pgvector_rejects_unsupported_embeddings_before_database_use(monkeypatch):
    monkeypatch.setattr(vector_store_module.settings, "DATABASE_URL", "postgresql+asyncpg://test")
    monkeypatch.setattr(vector_store_module.settings, "EMBEDDING_PROVIDER", "unsupported")
    with pytest.raises(RuntimeError, match="requires openai, sentence_transformers, or hashing"):
        PgvectorVectorStore()
