"""
Deterministic stand-in for a real LLM call (ChatOpenAI / Anthropic / etc).

This is the ONE component in the agent pipeline that genuinely requires a
paid API key in production and can't be faithfully replicated offline --
so rather than fake the *output* and pretend it's a real model, this stub
is explicit about what it is: an extractive, template-based responder built
from the actually-retrieved chunks. Everything AROUND it (the graph
routing, retrieval, streaming, tracing) is real and unchanged when you
swap this for ChatOpenAI -- that swap is exactly one line in graph_agent_v2.py.
"""
import asyncio
import random
from math import ceil
from typing import List, AsyncGenerator
from app.core.hybrid_retrieval import RetrievedChunk


class StubLLM:
    """Extractive responder: builds an answer from retrieved chunks with
    light templating, then yields it token-by-token to genuinely exercise
    the streaming pipeline (not just prove the final string is correct)."""

    GREETINGS = {"hi", "hello", "hey", "hi there", "hello there"}

    async def stream_answer(self, question: str, chunks: List[RetrievedChunk]) -> AsyncGenerator[str, None]:
        text = self._compose(question, chunks)
        for token in self._tokenize_for_streaming(text):
            yield token
            # Small randomized delay -- genuinely exercises the streaming
            # transport (not a fixed-size sleep that could hide buffering bugs)
            await asyncio.sleep(random.uniform(0.015, 0.045))

    async def stream_prompt(self, prompt: str) -> AsyncGenerator[str, None]:
        """Provider-compatible fallback entry point for the new LLM layer."""
        question = prompt.split("Question:", 1)[-1].strip().split("\n", 1)[0]
        context = prompt.split("Context:", 1)[-1].split("Question:", 1)[0].strip()
        chunks = [RetrievedChunk(id=f"context-{i}", text=part.strip()) for i, part in enumerate(context.split("\n---\n")) if part.strip()]
        async for token in self.stream_answer(question, chunks):
            yield token

    def usage_for_prompt(self, prompt: str, completion: str) -> dict:
        """Return realistic-shaped *estimated* usage for the zero-cost demo."""
        count = lambda text: max(1, ceil(len(text.strip()) / 4)) if text.strip() else 0
        return {
            "prompt_tokens": count(prompt),
            "completion_tokens": count(completion),
            "estimated_cost_usd": 0.0,
            "estimated": True,
        }

    def _compose(self, question: str, chunks: List[RetrievedChunk]) -> str:
        if question.strip().lower() in self.GREETINGS:
            return "Hello! Ask me something about your uploaded documents and I'll retrieve the relevant passages and answer from them."

        if not chunks:
            return "I couldn't find anything in the indexed documents relevant to that question. Try rephrasing, or upload a document that covers this topic."

        lead = f"Based on {len(chunks)} relevant passage{'s' if len(chunks) != 1 else ''} I found:\n\n"
        body_parts = []
        for i, c in enumerate(chunks, 1):
            source = c.metadata.get("source", c.id)
            body_parts.append(f"{i}. {c.text.strip()} (source: {source})")
        return lead + "\n".join(body_parts)

    def _tokenize_for_streaming(self, text: str) -> List[str]:
        # Stream word-by-word with the space attached, so the frontend can
        # just concatenate chunks directly without re-inserting whitespace.
        words = text.split(" ")
        return [w + " " for w in words]
