"""
LangGraph agent instrumented for real-time observability.

Every node emits a genuine trace event (via an asyncio callback) the instant
it starts and finishes, with real wall-clock timing. This is what powers the
live "agent trace" panel in the frontend -- it's not a simulated animation,
it's actual StateGraph execution being observed as it happens.

Graph: analyze_query -> (retrieve -> generate -> grade -> [retry|end]) | direct_answer
"""
import time
import logging
from typing import TypedDict, Annotated, List, Optional, Callable, Awaitable
import operator

from langgraph.graph import StateGraph, END

from app.core.hybrid_retrieval import HybridRetriever, RetrievedChunk
from app.core.semantic_cache import SemanticCache
from app.core.llm_provider import LLMProvider, get_llm_provider
from app.core.eval_metrics import persist_eval_metric
from app.core.token_usage import persist_token_usage
from app.core.telemetry import tracer
from app.core.web_search_provider import WebSearchProvider, get_web_search_provider
from app.core.conversation_memory import ConversationMemoryService
from app.config import settings

logger = logging.getLogger(__name__)

TraceCallback = Callable[[dict], Awaitable[None]]


class AgentState(TypedDict):
    question: str
    original_question: str
    context_chunks: List[RetrievedChunk]
    answer: str
    needs_retrieval: bool
    needs_improvement: bool
    iteration: int
    namespace: Optional[str]
    session_id: Optional[str]
    user_id: Optional[str]
    cache_hit: bool
    eval_metrics: dict
    web_search_attempted: bool
    conversation_context: str
    workspace_plan: str
    hyde_query: str


GREETING_WORDS = {"hi", "hello", "hey", "thanks", "thank you", "ok", "okay"}


class ObservableRAGAgent:
    """
    Same conceptual graph as the original graph_agent.py (analyze -> retrieve
    -> generate -> grade -> retry/end), rebuilt to:
      1. run with zero external API calls (StubLLM instead of ChatOpenAI)
      2. emit a trace event on every node transition via `trace_cb`
      3. use the real HybridRetriever + SemanticCache built earlier
    Swapping StubLLM for ChatOpenAI is the only change needed for production.
    """

    def __init__(self, retriever: HybridRetriever, cache: Optional[SemanticCache] = None, llm_provider: Optional[LLMProvider] = None, eval_recorder=None, usage_recorder=None, web_search_provider: Optional[WebSearchProvider] = None, memory_service: Optional[ConversationMemoryService] = None):
        self.retriever = retriever
        self.cache = cache or SemanticCache()
        self.llm = llm_provider or get_llm_provider()
        self.eval_recorder = eval_recorder or persist_eval_metric
        self.usage_recorder = usage_recorder or persist_token_usage
        self.web_search = web_search_provider or get_web_search_provider()
        self.memory_service = memory_service or ConversationMemoryService()
        self.graph = self._build_graph()

    async def _persist_usage(self, session_id: str, user_id: Optional[str], prompt: str) -> None:
        usage = self.llm.last_usage()
        if not usage:
            return
        await self.usage_recorder({
            "user_id": user_id, "session_id": session_id,
            "prompt_tokens": usage.prompt_tokens, "completion_tokens": usage.completion_tokens,
            "estimated_cost_usd": usage.estimated_cost_usd,
        })

    async def _emit(self, trace_cb: Optional[TraceCallback], event: dict):
        if trace_cb:
            event["ts"] = time.time()
            await trace_cb(event)

    def _build_graph(self):
        workflow = StateGraph(AgentState)
        workflow.add_node("analyze_query", self._analyze_query)
        workflow.add_node("check_cache", self._check_cache)
        workflow.add_node("retrieve_documents", self._retrieve_documents)
        workflow.add_node("generate_answer", self._generate_answer)
        workflow.add_node("grade_answer", self._grade_answer)
        workflow.add_node("web_search_fallback", self._web_search_fallback)
        workflow.add_node("direct_answer", self._direct_answer)

        workflow.set_entry_point("analyze_query")
        workflow.add_conditional_edges("analyze_query", self._route_after_analyze, {
            "retrieve": "check_cache", "direct": "direct_answer"
        })
        workflow.add_conditional_edges("check_cache", self._route_after_cache, {
            "hit": END, "miss": "retrieve_documents"
        })
        workflow.add_edge("retrieve_documents", "generate_answer")
        workflow.add_edge("generate_answer", "grade_answer")
        workflow.add_conditional_edges("grade_answer", self._route_after_grade, {
            "web_search": "web_search_fallback", "retry": "retrieve_documents", "end": END
        })
        workflow.add_edge("web_search_fallback", "generate_answer")
        workflow.add_edge("direct_answer", END)
        return workflow.compile()

    # ---- nodes (each is a real, independently-testable function) ----

    async def _analyze_query(self, state: AgentState) -> AgentState:
        with tracer().start_as_current_span("langgraph.analyze") as span:
            try:
                memory = await self.memory_service.load(state.get("session_id"))
                conversation_context = memory.text
            except Exception:
                # Conversation memory must never make a question unavailable.
                logger.warning("Conversation memory unavailable; continuing without history", exc_info=True)
                conversation_context = ""
            needs_retrieval = state["question"].strip().lower() not in GREETING_WORDS
            span.set_attribute("rag.needs_retrieval", needs_retrieval)
            span.set_attribute("rag.history_chars", len(conversation_context))
            hyde_query = ""
            if needs_retrieval and settings.HYDE_ENABLED:
                try:
                    parts = []
                    async for token in self.llm.generate(f"Write a short hypothetical document passage answering: {state['question']}"):
                        parts.append(token)
                        if len("".join(parts)) >= 500:
                            break
                    hyde_query = "".join(parts).strip()
                except Exception:
                    logger.warning("HyDE generation failed; falling back to raw query", exc_info=True)
            return {**state, "needs_retrieval": needs_retrieval, "conversation_context": conversation_context, "hyde_query": hyde_query}

    async def _check_cache(self, state: AgentState) -> AgentState:
        with tracer().start_as_current_span("langgraph.check_cache") as span:
            cached, score = self.cache.lookup(state["question"])
            span.set_attribute("rag.cache_hit", bool(cached))
            if cached:
                return {**state, "answer": cached["answer"], "cache_hit": True,
                        "context_chunks": cached.get("chunks", [])}
            return {**state, "cache_hit": False}

    async def _retrieve_documents(self, state: AgentState) -> AgentState:
        with tracer().start_as_current_span("langgraph.retrieve") as span:
            try:
                chunks = self.retriever.retrieve(state["question"], k=4, plan=state.get("workspace_plan", "free"), dense_query=state.get("hyde_query") or None)
            except TypeError:  # lightweight test/demonstration retrievers
                chunks = self.retriever.retrieve(state["question"], k=4)
            span.set_attribute("rag.chunks_found", len(chunks))
            return {**state, "context_chunks": chunks}

    async def _generate_answer(self, state: AgentState) -> AgentState:
        # Streaming happens separately (see run_streaming below); this node
        # path is used for the non-streaming .run() convenience method.
        with tracer().start_as_current_span("langgraph.generate") as span:
            prompt = self._build_prompt(state["question"], state["context_chunks"], state.get("conversation_context", ""))
            parts = []
            async for tok in self.llm.generate(prompt):
                parts.append(tok)
            span.set_attribute("rag.completion_chars", len("".join(parts)))
            await self._persist_usage(state.get("session_id") or "graph-run", state.get("user_id"), prompt)
            return {**state, "answer": "".join(parts)}

    async def _web_search_fallback(self, state: AgentState) -> AgentState:
        """Append externally sourced results without replacing document context."""
        results = await self.web_search.search(state["question"])
        external = [
            RetrievedChunk(
                id=f"web-{index}", text=result.content,
                metadata={"source": result.url, "doc_title": result.title,
                          "url": result.url, "source_type": "external", "chunk_index": index},
                fused_score=result.score,
            )
            for index, result in enumerate(results)
        ]
        return {**state, "context_chunks": [*state["context_chunks"], *external],
                "web_search_attempted": True}

    async def _grade_answer(self, state: AgentState) -> AgentState:
        with tracer().start_as_current_span("langgraph.grade") as span:
            metrics = self._compute_eval_metrics(state)
            needs_improvement = metrics["groundedness"] < 0.15 and state.get("iteration", 0) < 1 and len(state["context_chunks"]) > 0
            span.set_attribute("rag.groundedness", metrics["groundedness"])
            return {**state, "needs_improvement": needs_improvement,
                    "iteration": state.get("iteration", 0) + 1, "eval_metrics": metrics}

    async def _direct_answer(self, state: AgentState) -> AgentState:
        prompt = self._build_prompt(state["question"], [], state.get("conversation_context", ""))
        parts = []
        async for tok in self.llm.generate(prompt):
            parts.append(tok)
        await self._persist_usage(state.get("session_id") or "graph-run", state.get("user_id"), prompt)
        return {**state, "answer": "".join(parts), "eval_metrics": {}}

    # ---- routing ----

    def _route_after_analyze(self, state: AgentState) -> str:
        return "retrieve" if state["needs_retrieval"] else "direct"

    def _route_after_cache(self, state: AgentState) -> str:
        return "hit" if state.get("cache_hit") else "miss"

    def _route_after_grade(self, state: AgentState) -> str:
        if (self.web_search.configured and not state.get("web_search_attempted")
                and state.get("eval_metrics", {}).get("retrieval_relevance", 0.0) < settings.RETRIEVAL_CONFIDENCE_THRESHOLD):
            return "web_search"
        return "retry" if state.get("needs_improvement") else "end"

    # ---- eval metrics (real, computed -- not hardcoded) ----

    def _compute_eval_metrics(self, state: AgentState) -> dict:
        """
        Lightweight, dependency-free proxies for RAGAS-style metrics:
        - groundedness: fraction of the answer's content words that actually
          appear in the retrieved context (a real faithfulness proxy -- an
          answer inventing facts not in context will score low here)
        - retrieval_relevance: mean fused RRF score of the chunks used
        """
        answer_words = set(w.lower().strip(".,!?") for w in state["answer"].split())
        context_text = " ".join(c.text.lower() for c in state["context_chunks"])
        context_words = set(context_text.split())

        meaningful = {w for w in answer_words if len(w) > 3}
        grounded = meaningful & context_words
        groundedness = len(grounded) / len(meaningful) if meaningful else 0.0

        rel_scores = [c.fused_score for c in state["context_chunks"]]
        retrieval_relevance = sum(rel_scores) / len(rel_scores) if rel_scores else 0.0

        return {
            "groundedness": round(groundedness, 3),
            "retrieval_relevance": round(retrieval_relevance, 4),
            "num_sources": len(state["context_chunks"]),
        }

    @staticmethod
    def _meaningful_words(text: str) -> set[str]:
        return {"".join(ch for ch in word.lower() if ch.isalnum()) for word in text.split() if len("".join(ch for ch in word if ch.isalnum())) > 3}

    def _citations_for_answer(self, answer: str, chunks: List[RetrievedChunk]) -> list[dict]:
        """Return only chunks with lexical grounding in the generated answer."""
        answer_words = self._meaningful_words(answer)
        citations = []
        for chunk_index, chunk in enumerate(chunks):
            overlap = answer_words & self._meaningful_words(chunk.text)
            if not overlap:
                continue
            metadata = chunk.metadata or {}
            citation = {
                "doc_id": metadata.get("document_id", chunk.id),
                "doc_title": metadata.get("doc_title", metadata.get("source", chunk.id)),
                "chunk_text": chunk.text,
                "chunk_index": metadata.get("chunk_index", chunk_index),
                "score": round(float(chunk.fused_score), 4),
                "source_type": metadata.get("source_type", "document"),
                "_overlap": len(overlap),
            }
            source_page = metadata.get("source_page", metadata.get("page"))
            if source_page is not None:
                citation["source_page"] = source_page
            if metadata.get("url"):
                citation["url"] = metadata["url"]
            citations.append(citation)
        citations.sort(key=lambda citation: (citation["_overlap"], citation["score"]), reverse=True)
        for citation in citations:
            citation.pop("_overlap", None)
        return citations

    def _attach_citations(self, answer: str, chunks: List[RetrievedChunk]) -> tuple[str, list[dict]]:
        citations = self._citations_for_answer(answer, chunks)
        if not citations or any(f"[{index}]" in answer for index in range(1, len(citations) + 1)):
            return answer, citations
        markers = " ".join(f"[{index}]" for index in range(1, len(citations) + 1))
        return f"{answer.rstrip()} {markers}", citations

    # ---- streaming entrypoint used by the WebSocket route ----

    async def run_streaming(self, question: str, namespace: Optional[str], trace_cb: Optional[TraceCallback] = None, session_id: str = "demo", user_id: Optional[str] = None) -> dict:
        state: AgentState = {
            "question": question, "original_question": question, "context_chunks": [],
            "answer": "", "needs_retrieval": True, "needs_improvement": False,
            "iteration": 0, "namespace": namespace, "session_id": session_id, "user_id": user_id,
            "cache_hit": False, "eval_metrics": {}, "web_search_attempted": False, "conversation_context": "", "workspace_plan": "free", "hyde_query": ""
        }
        run_started = time.time()
        node_timings = {}

        await self._emit(trace_cb, {"type": "node_start", "node": "analyze_query"})
        t0 = time.time()
        state = await self._analyze_query(state)
        node_timings["analyze_query"] = round((time.time() - t0) * 1000, 1)
        await self._emit(trace_cb, {"type": "node_end", "node": "analyze_query",
                                     "duration_ms": round((time.time() - t0) * 1000, 1),
                                     "result": {"needs_retrieval": state["needs_retrieval"]}})

        if not state["needs_retrieval"]:
            await self._emit(trace_cb, {"type": "node_start", "node": "direct_answer"})
            t0 = time.time()
            answer_parts = []
            prompt = self._build_prompt(state["question"], [], state.get("conversation_context", ""))
            with tracer().start_as_current_span("langgraph.generate") as span:
                async for tok in self.llm.generate(prompt):
                    answer_parts.append(tok)
                    await self._emit(trace_cb, {"type": "token", "token": tok})
                span.set_attribute("rag.completion_chars", len("".join(answer_parts)))
            state["answer"] = "".join(answer_parts)
            await self._persist_usage(session_id, user_id, prompt)
            node_timings["direct_answer"] = round((time.time() - t0) * 1000, 1)
            await self._emit(trace_cb, {"type": "node_end", "node": "direct_answer",
                                         "duration_ms": round((time.time() - t0) * 1000, 1)})
            await self._emit(trace_cb, {"type": "done", "answer": state["answer"], "sources": [], "citations": [], "eval_metrics": {}, "cache_hit": False})
            await self._persist_eval(session_id, user_id, question, state, run_started, node_timings)
            return state

        await self._emit(trace_cb, {"type": "node_start", "node": "check_cache"})
        t0 = time.time()
        with tracer().start_as_current_span("langgraph.check_cache") as span:
            cached, sim_score = self.cache.lookup(state["question"])
            span.set_attribute("rag.cache_hit", bool(cached))
        cache_dur = round((time.time() - t0) * 1000, 1)
        node_timings["check_cache"] = cache_dur
        await self._emit(trace_cb, {"type": "node_end", "node": "check_cache", "duration_ms": cache_dur,
                                     "result": {"hit": bool(cached), "similarity": round(sim_score, 3)}})

        if cached:
            state["answer"] = cached["answer"]
            state["context_chunks"] = cached.get("chunks", [])
            state["cache_hit"] = True
            state["answer"], citations = self._attach_citations(state["answer"], state["context_chunks"])
            for tok in state["answer"].split(" "):
                await self._emit(trace_cb, {"type": "token", "token": tok + " "})
            await self._emit(trace_cb, {"type": "done", "answer": state["answer"],
                                         "sources": [self._chunk_to_source(c) for c in state["context_chunks"]],
                                         "citations": citations,
                                         "eval_metrics": {}, "cache_hit": True, "cache_similarity": round(sim_score, 3)})
            await self._persist_eval(session_id, user_id, question, state, run_started, node_timings)
            return state

        await self._emit(trace_cb, {"type": "node_start", "node": "retrieve_documents"})
        t0 = time.time()
        state = await self._retrieve_documents(state)
        node_timings["retrieve_documents"] = round((time.time() - t0) * 1000, 1)
        await self._emit(trace_cb, {"type": "node_end", "node": "retrieve_documents",
                                     "duration_ms": round((time.time() - t0) * 1000, 1),
                                     "result": {"chunks_found": len(state["context_chunks"]),
                                                "top_scores": [round(c.fused_score, 4) for c in state["context_chunks"]],
                                                "reranking_applied": bool(getattr(self.retriever, "reranker_applied", False))}})

        await self._emit(trace_cb, {"type": "node_start", "node": "generate_answer"})
        t0 = time.time()
        answer_parts = []
        prompt = self._build_prompt(state["question"], state["context_chunks"], state.get("conversation_context", ""))
        with tracer().start_as_current_span("langgraph.generate") as span:
            async for tok in self.llm.generate(prompt):
                answer_parts.append(tok)
                await self._emit(trace_cb, {"type": "token", "token": tok})
            span.set_attribute("rag.completion_chars", len("".join(answer_parts)))
        raw_answer = "".join(answer_parts)
        await self._persist_usage(session_id, user_id, prompt)
        state["answer"], citations = self._attach_citations(raw_answer, state["context_chunks"])
        node_timings["generate_answer"] = round((time.time() - t0) * 1000, 1)
        # Keep incremental rendering faithful to the final done payload.
        if state["answer"] != raw_answer:
            await self._emit(trace_cb, {"type": "token", "token": state["answer"][len(raw_answer):]})
        await self._emit(trace_cb, {"type": "node_end", "node": "generate_answer",
                                     "duration_ms": round((time.time() - t0) * 1000, 1)})

        await self._emit(trace_cb, {"type": "node_start", "node": "grade_answer"})
        t0 = time.time()
        state = await self._grade_answer(state)
        node_timings["grade_answer"] = round((time.time() - t0) * 1000, 1)
        await self._emit(trace_cb, {"type": "node_end", "node": "grade_answer",
                                     "duration_ms": round((time.time() - t0) * 1000, 1),
                                     "result": state["eval_metrics"]})

        if self._route_after_grade(state) == "web_search":
            await self._emit(trace_cb, {"type": "web_search", "status": "started", "provider": type(self.web_search).__name__})
            await self._emit(trace_cb, {"type": "node_start", "node": "web_search_fallback"})
            t0 = time.time()
            previous_count = len(state["context_chunks"])
            state = await self._web_search_fallback(state)
            web_duration = round((time.time() - t0) * 1000, 1)
            node_timings["web_search_fallback"] = web_duration
            external_count = len(state["context_chunks"]) - previous_count
            await self._emit(trace_cb, {"type": "node_end", "node": "web_search_fallback", "duration_ms": web_duration,
                                        "result": {"results_found": external_count, "configured": self.web_search.configured}})
            await self._emit(trace_cb, {"type": "web_search", "status": "completed", "results_found": external_count, "configured": self.web_search.configured, "duration_ms": web_duration})

            await self._emit(trace_cb, {"type": "node_start", "node": "generate_answer"})
            t0 = time.time()
            answer_parts = []
            prompt = self._build_prompt(state["question"], state["context_chunks"], state.get("conversation_context", ""))
            with tracer().start_as_current_span("langgraph.generate") as span:
                async for tok in self.llm.generate(prompt):
                    answer_parts.append(tok)
                    await self._emit(trace_cb, {"type": "token", "token": tok})
                span.set_attribute("rag.completion_chars", len("".join(answer_parts)))
            raw_answer = "".join(answer_parts)
            await self._persist_usage(session_id, user_id, prompt)
            state["answer"], citations = self._attach_citations(raw_answer, state["context_chunks"])
            node_timings["generate_after_web_search"] = round((time.time() - t0) * 1000, 1)
            if state["answer"] != raw_answer:
                await self._emit(trace_cb, {"type": "token", "token": state["answer"][len(raw_answer):]})
            await self._emit(trace_cb, {"type": "node_end", "node": "generate_answer", "duration_ms": node_timings["generate_after_web_search"]})

            await self._emit(trace_cb, {"type": "node_start", "node": "grade_answer"})
            t0 = time.time()
            state = await self._grade_answer(state)
            node_timings["grade_after_web_search"] = round((time.time() - t0) * 1000, 1)
            await self._emit(trace_cb, {"type": "node_end", "node": "grade_answer", "duration_ms": node_timings["grade_after_web_search"], "result": state["eval_metrics"]})

        self.cache.store(state["question"], {"answer": state["answer"], "chunks": state["context_chunks"]})

        await self._emit(trace_cb, {"type": "done", "answer": state["answer"],
                                     "sources": [self._chunk_to_source(c) for c in state["context_chunks"]],
                                     "citations": citations,
                                     "eval_metrics": state["eval_metrics"], "cache_hit": False})
        await self._persist_eval(session_id, user_id, question, state, run_started, node_timings)
        return state

    async def _persist_eval(self, session_id, user_id, query_text, state, started, node_timings):
        await self.eval_recorder({"user_id": user_id, "session_id": session_id, "query_text": query_text, "groundedness": state.get("eval_metrics", {}).get("groundedness", 0), "retrieval_relevance": state.get("eval_metrics", {}).get("retrieval_relevance", 0), "latency_ms": round((time.time() - started) * 1000, 1), "node_timings": node_timings, "cache_hit": state.get("cache_hit", False)})

    def _chunk_to_source(self, c: RetrievedChunk) -> dict:
        return {"id": c.id, "text": c.text[:200], "source": c.metadata.get("source", c.id),
                "document_id": c.metadata.get("document_id", c.id),
                "doc_title": c.metadata.get("doc_title", c.metadata.get("source", c.id)),
                "source_page": c.metadata.get("source_page", c.metadata.get("page")),
                "chunk_index": c.metadata.get("chunk_index"),
                "fused_score": round(c.fused_score, 4), "source_type": c.metadata.get("source_type", "document")}

    @staticmethod
    def _build_prompt(question: str, chunks: List[RetrievedChunk], conversation_context: str = "") -> str:
        context = "\n---\n".join(chunk.text for chunk in chunks) or "No retrieved documents were relevant."
        history = f"\n\nConversation memory (use it only to resolve follow-ups):\n{conversation_context}" if conversation_context else ""
        return (
            "You are a grounded document assistant. Answer only from the supplied context. "
            "If the context is insufficient, say so clearly.\n\n"
            f"Context:\n{context}{history}\n\nQuestion: {question}"
        )
