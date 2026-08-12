"""Provider-neutral document vector storage.

Chroma remains the default for local/demo use.  Pgvector uses the application's
Postgres database, so multiple API workers share the same embeddings.
"""
import json
import logging
from abc import ABC, abstractmethod
from typing import List, Optional, Tuple

from langchain_core.documents import Document
from sqlalchemy import text

from app.config import settings
from app.models.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


class HashingEmbeddings:
    """Small, deterministic embedding adapter for constrained deployments.

    It matches the LangChain embedding interface while avoiding Torch and model
    downloads.  It is intentionally a fallback-quality retrieval mode; BM25
    remains the strong exact-match leg in the hybrid pipeline.
    """
    def __init__(self, dimensions: int = 384):
        from sklearn.feature_extraction.text import HashingVectorizer
        self._vectorizer = HashingVectorizer(
            n_features=dimensions, alternate_sign=False, norm="l2", lowercase=True
        )

    def _encode(self, texts: List[str]) -> List[List[float]]:
        return self._vectorizer.transform(texts).toarray().astype("float32").tolist()

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self._encode(texts)

    def embed_query(self, text: str) -> List[float]:
        return self._encode([text])[0]


class LazySentenceTransformerEmbeddings:
    """Defer Torch/model allocation until the first ingestion or query.

    This lets health checks and low-memory hosts start without allocating the
    sentence-transformer model. The full semantic model is still used when a
    request actually calls ``embed_documents`` or ``embed_query``.
    """
    def __init__(self, model_name: str):
        self.model_name = model_name
        self._delegate = None

    def _get_delegate(self):
        if self._delegate is None:
            from langchain_community.embeddings import HuggingFaceEmbeddings
            self._delegate = HuggingFaceEmbeddings(model_name=self.model_name)
        return self._delegate

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self._get_delegate().embed_documents(texts)

    def embed_query(self, text: str) -> List[float]:
        return self._get_delegate().embed_query(text)


def create_embedding_function():
    """Return the embedding implementation selected by EMBEDDING_PROVIDER."""
    provider = settings.EMBEDDING_PROVIDER.strip().lower()
    if provider == "openai":
        if not settings.OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY is required for EMBEDDING_PROVIDER=openai")
        from langchain_openai import OpenAIEmbeddings
        return OpenAIEmbeddings(model=settings.EMBEDDING_MODEL, openai_api_key=settings.OPENAI_API_KEY)
    if provider in {"", "sentence_transformers", "sentence-transformers"}:
        return LazySentenceTransformerEmbeddings(settings.SENTENCE_TRANSFORMER_MODEL)
    if provider == "hashing":
        return HashingEmbeddings(settings.PGVECTOR_DIMENSIONS)
    raise ValueError(f"Unsupported EMBEDDING_PROVIDER: {provider}")


class VectorStoreBackend(ABC):
    @abstractmethod
    async def add_documents(self, documents: List[Document], user_id: str, workspace_id: str, namespace: Optional[str] = None) -> List[str]: ...

    @abstractmethod
    async def similarity_search(self, query: str, user_id: str, workspace_id: str, k: int = 5, namespace: Optional[str] = None, score_threshold: float = .5) -> List[Tuple[Document, float]]: ...

    @abstractmethod
    async def delete_documents(self, ids: List[str]) -> bool: ...

    @abstractmethod
    def get_retriever(self, user_id: str, workspace_id: str, k: int = 5, namespace: Optional[str] = None): ...


class ChromaVectorStore(VectorStoreBackend):
    """Existing Chroma implementation, kept unchanged behind the contract."""
    def __init__(self):
        import chromadb
        from chromadb.config import Settings as ChromaSettings
        from langchain_community.vectorstores import Chroma
        self.embeddings = create_embedding_function()
        self.chroma_client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR, settings=ChromaSettings(anonymized_telemetry=False))
        self.vector_store = Chroma(client=self.chroma_client, collection_name=settings.CHROMA_COLLECTION_NAME, embedding_function=self.embeddings)

    @staticmethod
    def _where(workspace_id: str, namespace: Optional[str] = None) -> dict:
        clauses = [{"workspace_id": workspace_id}]
        if namespace:
            clauses.append({"namespace": namespace})
        return clauses[0] if len(clauses) == 1 else {"$and": clauses}

    async def add_documents(self, documents, user_id, workspace_id, namespace=None):
        for document in documents:
            document.metadata.update({"user_id": user_id, "workspace_id": workspace_id})
            if namespace:
                document.metadata["namespace"] = namespace
        return self.vector_store.add_documents(documents)

    async def similarity_search(self, query, user_id, workspace_id, k=5, namespace=None, score_threshold=.5):
        return self.vector_store.similarity_search_with_relevance_scores(query=query, k=k, filter=self._where(workspace_id, namespace), score_threshold=score_threshold)

    async def delete_documents(self, ids):
        self.vector_store.delete(ids=ids)
        return True

    def get_retriever(self, user_id, workspace_id, k=5, namespace=None):
        return self.vector_store.as_retriever(search_type="similarity", search_kwargs={"k": k, "filter": self._where(workspace_id, namespace)})


def _pgvector_literal(values: List[float]) -> str:
    """Postgres vector input, passed as a bound parameter rather than SQL text."""
    return "[" + ",".join(f"{float(value):.8g}" for value in values) + "]"


class PgvectorRetriever:
    def __init__(self, store: "PgvectorVectorStore", user_id: str, workspace_id: str, k: int, namespace: str | None):
        self.store, self.user_id, self.workspace_id, self.k, self.namespace = store, user_id, workspace_id, k, namespace

    async def aget_relevant_documents(self, query: str) -> List[Document]:
        return [document for document, _ in await self.store.similarity_search(query, self.user_id, self.workspace_id, self.k, self.namespace)]

    async def ainvoke(self, query: str) -> List[Document]:
        return await self.aget_relevant_documents(query)


class PgvectorVectorStore(VectorStoreBackend):
    """Postgres/pgvector implementation of the same storage contract.

    HNSW is chosen over IVFFlat because the project starts with small and
    continuously changing per-workspace corpora. HNSW needs no training/list
    tuning and preserves useful recall immediately after inserts.
    """
    def __init__(self):
        if not settings.DATABASE_URL.startswith("postgresql"):
            raise RuntimeError("VECTOR_STORE_PROVIDER=pgvector requires a PostgreSQL DATABASE_URL")
        if settings.EMBEDDING_PROVIDER.strip().lower() not in {"openai", "sentence_transformers", "sentence-transformers", "hashing"}:
            raise RuntimeError("VECTOR_STORE_PROVIDER=pgvector requires openai, sentence_transformers, or hashing embeddings")
        self.embeddings = create_embedding_function()
        self.table = settings.PGVECTOR_TABLE_NAME
        if not self.table.replace("_", "").isalnum():
            raise ValueError("PGVECTOR_TABLE_NAME may contain only letters, numbers, and underscores")

    async def add_documents(self, documents, user_id, workspace_id, namespace=None):
        contents = [document.page_content for document in documents]
        vectors = self.embeddings.embed_documents(contents)
        ids = []
        statement = text(f"""INSERT INTO {self.table}
            (id, user_id, workspace_id, namespace, content, metadata, embedding)
            VALUES (:id, :user_id, :workspace_id, :namespace, :content,
                    CAST(:metadata AS jsonb), CAST(:embedding AS vector))""")
        import uuid
        async with AsyncSessionLocal() as session:
            for document, vector in zip(documents, vectors):
                identifier = str(uuid.uuid4())
                metadata = {**document.metadata, "user_id": user_id, "workspace_id": workspace_id}
                if namespace:
                    metadata["namespace"] = namespace
                await session.execute(statement, {"id": identifier, "user_id": user_id, "workspace_id": workspace_id, "namespace": namespace or "default", "content": document.page_content, "metadata": json.dumps(metadata), "embedding": _pgvector_literal(vector)})
                ids.append(identifier)
            await session.commit()
        return ids

    async def similarity_search(self, query, user_id, workspace_id, k=5, namespace=None, score_threshold=.5):
        vector = _pgvector_literal(self.embeddings.embed_query(query))
        where_namespace = "AND namespace = :namespace" if namespace else ""
        statement = text(f"""SELECT id, content, metadata, 1 - (embedding <=> CAST(:embedding AS vector)) AS score
            FROM {self.table}
            WHERE workspace_id = :workspace_id {where_namespace}
              AND 1 - (embedding <=> CAST(:embedding AS vector)) >= :score_threshold
            ORDER BY embedding <=> CAST(:embedding AS vector) LIMIT :limit""")
        params = {"embedding": vector, "workspace_id": workspace_id, "score_threshold": score_threshold, "limit": k}
        if namespace:
            params["namespace"] = namespace
        async with AsyncSessionLocal() as session:
            rows = (await session.execute(statement, params)).mappings().all()
        return [(Document(page_content=row["content"], metadata=row["metadata"] or {}), float(row["score"])) for row in rows]

    async def delete_documents(self, ids):
        if not ids:
            return True
        async with AsyncSessionLocal() as session:
            await session.execute(text(f"DELETE FROM {self.table} WHERE id = ANY(:ids)"), {"ids": ids})
            await session.commit()
        return True

    def get_retriever(self, user_id, workspace_id, k=5, namespace=None):
        return PgvectorRetriever(self, user_id, workspace_id, k, namespace)


class VectorStoreManager(VectorStoreBackend):
    """Select the configured backend while preserving the existing public API."""
    def __init__(self):
        provider = settings.VECTOR_STORE_PROVIDER.strip().lower()
        if provider == "chroma":
            self.backend: VectorStoreBackend = ChromaVectorStore()
        elif provider == "pgvector":
            self.backend = PgvectorVectorStore()
        else:
            raise ValueError(f"Unsupported VECTOR_STORE_PROVIDER: {provider}")
        logger.info("VectorStore initialized with provider=%s", provider)

    async def add_documents(self, *args, **kwargs): return await self.backend.add_documents(*args, **kwargs)
    async def similarity_search(self, *args, **kwargs): return await self.backend.similarity_search(*args, **kwargs)
    async def delete_documents(self, *args, **kwargs): return await self.backend.delete_documents(*args, **kwargs)
    def get_retriever(self, *args, **kwargs): return self.backend.get_retriever(*args, **kwargs)
