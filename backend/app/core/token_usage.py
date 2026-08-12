"""Best-effort persistence for per-user LLM token and cost estimates."""
import logging
from datetime import datetime
from typing import Any

from app.models.database import AsyncSessionLocal, TokenUsage

logger = logging.getLogger(__name__)


def summarize_usage(records: list[TokenUsage]) -> dict:
    """Shared aggregate used by analytics and workspace quota enforcement."""
    return {
        "requests": len(records),
        "prompt_tokens": sum(int(record.prompt_tokens or 0) for record in records),
        "completion_tokens": sum(int(record.completion_tokens or 0) for record in records),
        "tokens": sum(int(record.prompt_tokens or 0) + int(record.completion_tokens or 0) for record in records),
        "estimated_cost_usd": round(sum(float(record.estimated_cost_usd or 0) for record in records), 8),
    }


async def persist_token_usage(record: dict[str, Any]) -> None:
    """Never let an analytics write turn a successful answer into an error."""
    try:
        async with AsyncSessionLocal() as session:
            session.add(TokenUsage(**record))
            await session.commit()
    except Exception:
        logger.exception("Could not persist token usage")
