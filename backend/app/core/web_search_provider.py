"""Optional web-search providers for the low-confidence RAG fallback."""
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class WebSearchResult:
    title: str
    content: str
    url: str
    score: float = 0.0


class WebSearchProvider(ABC):
    configured: bool = False

    @abstractmethod
    async def search(self, query: str) -> list[WebSearchResult]:
        """Return concise, source-attributed results for a query."""


class NoopWebSearchProvider(WebSearchProvider):
    """Boot-safe provider used when no external search credentials exist."""
    configured = False

    async def search(self, query: str) -> list[WebSearchResult]:
        logger.warning("Web search fallback skipped: no provider/API key is configured")
        return []


class TavilyProvider(WebSearchProvider):
    configured = True

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def search(self, query: str) -> list[WebSearchResult]:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    "https://api.tavily.com/search",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "query": query,
                        "search_depth": "basic",
                        "max_results": settings.WEB_SEARCH_MAX_RESULTS,
                        "include_answer": False,
                    },
                )
                response.raise_for_status()
        except httpx.HTTPError as error:
            logger.warning("Tavily web search failed; continuing without external context: %s", error)
            return []

        return [
            WebSearchResult(
                title=item.get("title") or item.get("url") or "External web result",
                content=item.get("content", ""),
                url=item.get("url", ""),
                score=float(item.get("score") or 0.0),
            )
            for item in response.json().get("results", [])
            if item.get("content")
        ]


def get_web_search_provider() -> WebSearchProvider:
    provider = settings.WEB_SEARCH_PROVIDER.strip().lower()
    if provider in {"", "auto", "tavily"} and settings.TAVILY_API_KEY:
        return TavilyProvider(settings.TAVILY_API_KEY)
    if provider not in {"", "auto", "tavily", "none", "disabled"}:
        logger.warning("Unknown WEB_SEARCH_PROVIDER=%s; skipping web fallback", provider)
    return NoopWebSearchProvider()
