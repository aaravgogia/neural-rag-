from __future__ import annotations
import logging
from typing import List, Optional, AsyncGenerator, TYPE_CHECKING

try:  # Lazy-compatible so safety tests/demo tooling do not need production LLM SDKs.
    from langchain_openai import ChatOpenAI
    from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
    from langchain.schema import BaseMessage
except ImportError:  # pragma: no cover - production requirements provide these
    ChatOpenAI = ChatPromptTemplate = MessagesPlaceholder = None
    BaseMessage = object

from app.config import settings
from app.core.prompt_safety import filter_retrieved_chunks
if TYPE_CHECKING:
    from app.core.vector_store import VectorStoreManager

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert AI assistant for an Enterprise Document Intelligence Platform.
Answer based on the provided context. If information is not in context, say so clearly.
Cite sources when possible. Be concise, professional, and accurate.

Context:
{context}
"""

class RAGPipeline:
    """Simple (non-agentic) LangChain RAG pipeline."""

    def __init__(self, vector_store: VectorStoreManager):
        if ChatOpenAI is None:
            raise RuntimeError("RAGPipeline requires the full production LangChain/OpenAI dependencies")
        self.vector_store = vector_store
        self.llm = ChatOpenAI(
            model=settings.LLM_MODEL,
            temperature=settings.TEMPERATURE,
            max_tokens=settings.MAX_TOKENS,
            openai_api_key=settings.OPENAI_API_KEY,
            streaming=True
        )
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_PROMPT),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{question}")
        ])

    def _format_docs(self, docs) -> str:
        formatted = []
        for i, (doc, score) in enumerate(docs):
            source = doc.metadata.get("source", "Unknown")
            page = doc.metadata.get("page", "N/A")
            formatted.append(f"[Source {i+1}: {source}, Page: {page}]\n{doc.page_content}")
        return "\n\n---\n\n".join(formatted)

    @staticmethod
    def _safe_docs(docs):
        safe, excluded = filter_retrieved_chunks(docs)
        if excluded:
            logger.warning("Excluded %d retrieved chunk(s) before LLM context construction", len(excluded))
        return safe

    async def query(self, question: str, user_id: str, workspace_id: str, chat_history: Optional[List[BaseMessage]] = None, namespace: Optional[str] = None) -> dict:
        relevant_docs = await self.vector_store.similarity_search(
            query=question, user_id=user_id, workspace_id=workspace_id, k=settings.TOP_K_RESULTS, namespace=namespace
        )
        relevant_docs = self._safe_docs(relevant_docs)
        context = self._format_docs(relevant_docs)
        messages = self.prompt.format_messages(context=context, chat_history=chat_history or [], question=question)
        response = await self.llm.ainvoke(messages)

        sources = [
            {
                "content": doc.page_content[:200],
                "source": doc.metadata.get("source", "Unknown"),
                "page": doc.metadata.get("page", "N/A"),
                "source_page": doc.metadata.get("source_page"),
                "chunk_index": doc.metadata.get("chunk_index"),
                "score": float(score),
                "document_id": doc.metadata.get("document_id"),
                "doc_title": doc.metadata.get("doc_title", doc.metadata.get("source", "Unknown")),
            }
            for doc, score in relevant_docs
        ]
        return {"answer": response.content, "sources": sources, "question": question}

    async def stream_query(self, question: str, user_id: str, workspace_id: str, chat_history: Optional[List[BaseMessage]] = None, namespace: Optional[str] = None) -> AsyncGenerator[str, None]:
        relevant_docs = await self.vector_store.similarity_search(
            query=question, user_id=user_id, workspace_id=workspace_id, k=settings.TOP_K_RESULTS, namespace=namespace
        )
        relevant_docs = self._safe_docs(relevant_docs)
        context = self._format_docs(relevant_docs)
        messages = self.prompt.format_messages(context=context, chat_history=chat_history or [], question=question)
        async for chunk in self.llm.astream(messages):
            if chunk.content:
                yield chunk.content
