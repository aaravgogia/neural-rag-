"""Small, transparent retrieval-time prompt-injection filter."""
import logging
import re
from typing import Iterable

logger = logging.getLogger(__name__)

_INJECTION_PATTERNS = (
    re.compile(r"\bignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions?\b", re.I),
    re.compile(r"\b(disregard|override)\s+(?:the\s+)?(?:system|developer|previous)\s+(?:prompt|instructions?)\b", re.I),
    re.compile(r"\b(?:system|developer)\s*:\s*", re.I),
    re.compile(r"\b(?:you are|act as)\s+(?:chatgpt|an?\s+system|an?\s+assistant)\b", re.I),
    re.compile(r"<\/?(?:system|assistant|developer)>", re.I),
)


def is_prompt_injection(text: str) -> bool:
    return any(pattern.search(text or "") for pattern in _INJECTION_PATTERNS)


def filter_retrieved_chunks(docs: Iterable[tuple]) -> tuple[list[tuple], list[tuple]]:
    """Return (safe, excluded) and make every exclusion observable in logs."""
    safe, excluded = [], []
    for doc, score in docs:
        if is_prompt_injection(doc.page_content):
            logger.warning("Excluded prompt-injection-like retrieved chunk from source=%s", doc.metadata.get("source", "unknown"))
            excluded.append((doc, score))
        else:
            safe.append((doc, score))
    return safe, excluded
