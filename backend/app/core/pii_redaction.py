"""PII redaction before vectorisation, with a no-crash Presidio fallback."""
import logging
import re
from dataclasses import dataclass

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Redaction:
    entity_type: str
    start: int
    end: int
    original_value: str
    replacement: str


class PIIRedactor:
    """Uses Presidio when its full production dependencies are available."""

    _fallback_patterns = (
        ("EMAIL_ADDRESS", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)),
        ("US_SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
        ("PHONE_NUMBER", re.compile(r"\b(?:\+?1[ .-]?)?(?:\(?\d{3}\)?[ .-]?)\d{3}[ .-]\d{4}\b")),
    )

    def __init__(self):
        self._analyzer = None
        self._presidio_checked = False

    def _presidio(self):
        if self._presidio_checked:
            return self._analyzer
        self._presidio_checked = True
        try:
            from presidio_analyzer import AnalyzerEngine
            from presidio_analyzer.nlp_engine import NlpEngineProvider
            engine = NlpEngineProvider(nlp_configuration={
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": "en", "model_name": settings.PRESIDIO_SPACY_MODEL}],
            }).create_engine()
            self._analyzer = AnalyzerEngine(nlp_engine=engine)
            logger.info("Presidio PII analyzer enabled with %s", settings.PRESIDIO_SPACY_MODEL)
        except Exception as error:
            # The spaCy model is intentionally absent from the lightweight demo.
            logger.warning("Presidio/spaCy unavailable; using limited regex PII fallback: %s", error)
        return self._analyzer

    def redact(self, text: str) -> tuple[str, list[Redaction]]:
        if not settings.PII_REDACTION_ENABLED or not text:
            return text, []
        analyzer = self._presidio()
        if analyzer:
            try:
                findings = analyzer.analyze(text=text, language="en")
                matches = [(item.entity_type, item.start, item.end) for item in findings]
            except Exception as error:
                logger.warning("Presidio analysis failed; using limited regex PII fallback: %s", error)
                matches = self._fallback_matches(text)
        else:
            matches = self._fallback_matches(text)
        return self._apply(text, matches)

    def _fallback_matches(self, text: str) -> list[tuple[str, int, int]]:
        return [(kind, match.start(), match.end()) for kind, pattern in self._fallback_patterns for match in pattern.finditer(text)]

    @staticmethod
    def _apply(text: str, matches: list[tuple[str, int, int]]) -> tuple[str, list[Redaction]]:
        # Resolve overlapping findings before constructing replacements right to
        # left so offsets stay tied to the source document.
        accepted: list[tuple[str, int, int]] = []
        for kind, start, end in sorted(matches, key=lambda item: (item[1], -(item[2] - item[1]))):
            if not any(start < kept_end and end > kept_start for _, kept_start, kept_end in accepted):
                accepted.append((kind, start, end))
        counters: dict[str, int] = {}
        redactions = []
        for kind, start, end in accepted:
            counters[kind] = counters.get(kind, 0) + 1
            redactions.append(Redaction(kind, start, end, text[start:end], f"<{kind}_{counters[kind]}>"))
        redacted = text
        for item in reversed(redactions):
            redacted = redacted[:item.start] + item.replacement + redacted[item.end:]
        return redacted, redactions
