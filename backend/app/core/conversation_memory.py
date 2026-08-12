"""Durable, bounded conversation context keyed by the existing chat-session id."""
from dataclasses import dataclass
from typing import Callable

import tiktoken
from sqlalchemy import select

from app.config import settings
from app.models.database import AsyncSessionLocal, ChatMessage, ConversationMemory


@dataclass
class ConversationContext:
    text: str = ""
    summary: str = ""
    recent_messages: int = 0


class ConversationMemoryService:
    """Loads recent turns and persistently compacts older turns without an LLM call."""

    def __init__(self, session_factory: Callable = AsyncSessionLocal, *, recent_limit: int | None = None,
                 token_budget: int | None = None):
        self.session_factory = session_factory
        self.recent_limit = recent_limit or settings.CONVERSATION_HISTORY_MESSAGES
        self.token_budget = token_budget or settings.CONVERSATION_HISTORY_TOKEN_BUDGET
        try:
            self.encoding = tiktoken.get_encoding("cl100k_base")
        except Exception:
            # tiktoken lazily downloads encoding ranks on a completely cold
            # host.  Memory stays usable during an offline/demo boot while
            # production hosts with the cache retain exact token accounting.
            self.encoding = None

    def token_count(self, text: str) -> int:
        return len(self.encoding.encode(text)) if self.encoding else len(text.split())

    def _truncate_tokens(self, text: str, limit: int) -> str:
        if limit <= 0:
            return ""
        if self.encoding:
            tokens = self.encoding.encode(text)
            return self.encoding.decode(tokens[:limit])
        return " ".join(text.split()[:limit])

    @staticmethod
    def _role_label(message: ChatMessage) -> str:
        return "User" if message.role in {"human", "user"} else "Assistant"

    def _format_messages(self, messages: list[ChatMessage]) -> str:
        return "\n".join(f"{self._role_label(message)}: {message.content}" for message in messages)

    def _compact(self, existing: str, messages: list[ChatMessage]) -> str:
        """An extractive running summary preserves facts without a second provider call."""
        pieces = [existing.strip()] if existing.strip() else []
        for message in messages:
            content = " ".join(message.content.split())
            if content:
                pieces.append(f"{self._role_label(message)}: {content}")
        # Keep the stored summary compact even after a very long session.
        return self._truncate_tokens("\n".join(pieces), self.token_budget)

    async def load(self, conversation_id: str | None) -> ConversationContext:
        if not conversation_id:
            return ConversationContext()
        async with self.session_factory() as db:
            messages = list((await db.execute(
                select(ChatMessage).where(ChatMessage.session_id == conversation_id)
                .order_by(ChatMessage.created_at, ChatMessage.id)
            )).scalars())
            if not messages:
                return ConversationContext()

            recent = messages[-self.recent_limit:]
            older = messages[:-self.recent_limit]
            memory = (await db.execute(
                select(ConversationMemory).where(ConversationMemory.conversation_id == conversation_id)
            )).scalar_one_or_none()
            summary = memory.summary if memory else ""
            summarized_count = memory.summarized_message_count if memory else 0

            if len(older) > summarized_count:
                summary = self._compact(summary, older[summarized_count:])
                if memory is None:
                    memory = ConversationMemory(conversation_id=conversation_id)
                    db.add(memory)
                memory.summary = summary
                memory.summarized_message_count = len(older)
                await db.commit()

            recent_text = self._format_messages(recent)
            summary_text = f"Conversation summary:\n{summary}" if summary else ""
            # Recent messages retain priority; only the persisted older-turn
            # summary is shortened when the configured prompt budget is tight.
            remaining = self.token_budget - self.token_count(recent_text)
            if summary_text and remaining < self.token_count(summary_text):
                summary_text = f"Conversation summary:\n{self._truncate_tokens(summary, max(remaining - 4, 0))}"
            text = "\n\n".join(part for part in (summary_text, f"Recent conversation:\n{recent_text}") if part)
            return ConversationContext(text=text, summary=summary, recent_messages=len(recent))
