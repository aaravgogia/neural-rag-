from __future__ import annotations
import logging
from typing import List, Optional, AsyncGenerator, TYPE_CHECKING, Any

from app.config import settings
from app.core.llm_provider import LLMProvider, get_llm_provider
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

    def __init__(self, vector_store: VectorStoreManager, llm_provider: LLMProvider | None = None):
        self.vector_store = vector_store
        # The non-agent chat endpoint must use the same provider selection as
        # the LangGraph path.  Creating ChatOpenAI here previously made a
        # Mistral/Anthropic/Gemini deployment crash at boot without an OpenAI
        # key, despite the configured provider being healthy.
        self.llm = llm_provider or get_llm_provider()

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

    @staticmethod
    def _history_text(chat_history: Optional[List[Any]]) -> str:
        """Render optional LangChain-style history without requiring LangChain."""
        if not chat_history:
            return ""
        rendered = []
        for message in chat_history:
            content = getattr(message, "content", str(message))
            role = getattr(message, "type", message.__class__.__name__).replace("Message", "")
            rendered.append(f"{role}: {content}")
        return "\n".join(rendered)

    def _build_prompt(self, context: str, question: str, chat_history: Optional[List[Any]]) -> str:
        history = self._history_text(chat_history)
        history_section = f"\nConversation history:\n{history}\n" if history else ""
        return f"{SYSTEM_PROMPT.format(context=context)}{history_section}\nQuestion: {question}\nAnswer:"

    async def query(self, question: str, user_id: str, workspace_id: str, chat_history: Optional[List[Any]] = None, namespace: Optional[str] = None) -> dict:
        relevant_docs = await self.vector_store.similarity_search(
            query=question, user_id=user_id, workspace_id=workspace_id, k=settings.TOP_K_RESULTS, namespace=namespace
        )
        relevant_docs = self._safe_docs(relevant_docs)
        context = self._format_docs(relevant_docs)
        prompt = self._build_prompt(context, question, chat_history)
        response = "".join([chunk async for chunk in self.llm.generate(prompt, stream=False)])

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
        return {"answer": response, "sources": sources, "question": question}

    async def stream_query(self, question: str, user_id: str, workspace_id: str, chat_history: Optional[List[Any]] = None, namespace: Optional[str] = None) -> AsyncGenerator[str, None]:
        relevant_docs = await self.vector_store.similarity_search(
            query=question, user_id=user_id, workspace_id=workspace_id, k=settings.TOP_K_RESULTS, namespace=namespace
        )
        relevant_docs = self._safe_docs(relevant_docs)
        context = self._format_docs(relevant_docs)
        prompt = self._build_prompt(context, question, chat_history)
        async for chunk in self.llm.generate(prompt, stream=True):
            if chunk:
                yield chunk
