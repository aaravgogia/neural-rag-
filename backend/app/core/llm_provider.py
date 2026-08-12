"""Pluggable LLM generation with an always-available offline fallback."""
import logging
import inspect
from importlib.util import find_spec
from abc import ABC, abstractmethod
from contextvars import ContextVar
from dataclasses import dataclass
from math import ceil
from typing import AsyncIterator, Any

from app.config import settings
from app.core.stub_llm import StubLLM

logger = logging.getLogger(__name__)


def llm_runtime_status() -> str:
    """Describe the configured provider without making a network request."""
    requested = settings.LLM_PROVIDER.strip().lower() or "auto"
    candidates = [requested] if requested != "auto" else ["openai", "anthropic", "mistral", "gemini"]
    definitions = {
        "openai": ("OPENAI_API_KEY", settings.OPENAI_API_KEY, "langchain_openai", "ChatOpenAI"),
        "anthropic": ("ANTHROPIC_API_KEY", settings.ANTHROPIC_API_KEY, "langchain_anthropic", "ChatAnthropic"),
        "mistral": ("MISTRAL_API_KEY", settings.MISTRAL_API_KEY, "langchain_mistralai", "ChatMistralAI"),
        "gemini": ("GEMINI_API_KEY", settings.GEMINI_API_KEY, "google.genai", "Gemini GenAI"),
    }
    for candidate in candidates:
        definition = definitions.get(candidate)
        if not definition:
            return f"StubLLM (unsupported LLM_PROVIDER={requested!r})"
        key_name, api_key, package, class_name = definition
        if api_key and find_spec(package):
            return f"{class_name} (real; LLM_PROVIDER={candidate})"
        if api_key:
            return f"StubLLM ({package} is not installed)"
    required = " / ".join(definitions[c][0] for c in candidates if c in definitions)
    return f"StubLLM (no {required} found)"


@dataclass(frozen=True)
class LLMUsage:
    """Provider-reported usage where available; otherwise a documented estimate."""
    prompt_tokens: int
    completion_tokens: int
    estimated_cost_usd: float
    estimated: bool = False


def _estimated_tokens(text: str) -> int:
    # A stable approximation is preferable to pretending StubLLM has provider
    # accounting. It also covers SDKs that omit streaming usage metadata.
    return max(1, ceil(len(text.strip()) / 4)) if text.strip() else 0


def _usage_from_metadata(metadata: Any, prompt: str, completion: str, input_rate: float, output_rate: float) -> LLMUsage:
    data = metadata or {}
    if isinstance(data, dict) and "usage" in data and isinstance(data["usage"], dict):
        data = data["usage"]
    if not isinstance(data, dict):
        data = {}
    prompt_tokens = data.get("input_tokens", data.get("prompt_tokens", data.get("prompt_token_count")))
    completion_tokens = data.get("output_tokens", data.get("completion_tokens", data.get("candidates_token_count")))
    estimated = prompt_tokens is None or completion_tokens is None
    prompt_tokens = int(prompt_tokens if prompt_tokens is not None else _estimated_tokens(prompt))
    completion_tokens = int(completion_tokens if completion_tokens is not None else _estimated_tokens(completion))
    return LLMUsage(prompt_tokens, completion_tokens, round((prompt_tokens * input_rate + completion_tokens * output_rate) / 1000, 8), estimated)


class LLMProvider(ABC):
    _usage_context: ContextVar[LLMUsage | None] = ContextVar("llm_usage", default=None)

    @abstractmethod
    async def generate(self, prompt: str, stream: bool = True) -> AsyncIterator[str]:
        """Yield generated text chunks. `stream=False` yields one complete chunk."""
        yield ""  # pragma: no cover - abstract async generator marker

    def last_usage(self) -> LLMUsage | None:
        """Usage for this async request, isolated from concurrent streams."""
        return self._usage_context.get()

    def _set_usage(self, usage: LLMUsage) -> None:
        self._usage_context.set(usage)


class StubProvider(LLMProvider):
    """Offline provider used when keys or optional SDKs are unavailable."""
    def __init__(self, stub: StubLLM | None = None):
        self.stub = stub or StubLLM()

    async def generate(self, prompt: str, stream: bool = True) -> AsyncIterator[str]:
        chunks = [token async for token in self.stub.stream_prompt(prompt)]
        completion = "".join(chunks)
        # Demo usage deliberately has production-like token fields but no
        # billable cost: no paid provider was called.
        usage = self.stub.usage_for_prompt(prompt, completion)
        self._set_usage(LLMUsage(**usage))
        if stream:
            for token in chunks:
                yield token
        else:
            yield "".join(chunks)


class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str, model: str | None = None):
        from langchain_openai import ChatOpenAI
        self.client = ChatOpenAI(model=model or settings.LLM_MODEL, api_key=api_key, temperature=settings.TEMPERATURE)

    async def generate(self, prompt: str, stream: bool = True) -> AsyncIterator[str]:
        chunks, usage_metadata = [], None
        if stream:
            async for chunk in self.client.astream(prompt):
                if chunk.content:
                    text = str(chunk.content)
                    chunks.append(text)
                    usage_metadata = getattr(chunk, "usage_metadata", None) or usage_metadata
                    yield text
        else:
            response = await self.client.ainvoke(prompt)
            chunks.append(str(response.content))
            usage_metadata = getattr(response, "usage_metadata", None) or getattr(response, "response_metadata", None)
            yield chunks[0]
        self._set_usage(_usage_from_metadata(usage_metadata, prompt, "".join(chunks), .00015, .0006))


class AnthropicProvider(LLMProvider):
    def __init__(self, api_key: str, model: str | None = None):
        from langchain_anthropic import ChatAnthropic
        self.client = ChatAnthropic(model=model or settings.ANTHROPIC_MODEL, api_key=api_key, temperature=settings.TEMPERATURE)

    async def generate(self, prompt: str, stream: bool = True) -> AsyncIterator[str]:
        chunks, usage_metadata = [], None
        if stream:
            async for chunk in self.client.astream(prompt):
                if chunk.content:
                    text = str(chunk.content)
                    chunks.append(text)
                    usage_metadata = getattr(chunk, "usage_metadata", None) or usage_metadata
                    yield text
        else:
            response = await self.client.ainvoke(prompt)
            chunks.append(str(response.content))
            usage_metadata = getattr(response, "usage_metadata", None) or getattr(response, "response_metadata", None)
            yield chunks[0]
        self._set_usage(_usage_from_metadata(usage_metadata, prompt, "".join(chunks), .003, .015))

class MistralProvider(LLMProvider):
    def __init__(self, api_key: str, model: str | None = None):
        from langchain_mistralai import ChatMistralAI
        self.client = ChatMistralAI(model=model or settings.MISTRAL_MODEL, api_key=api_key, temperature=settings.TEMPERATURE)
    async def generate(self, prompt: str, stream: bool = True) -> AsyncIterator[str]:
        chunks, metadata = [], None
        async for chunk in self.client.astream(prompt):
            if chunk.content:
                text = str(chunk.content); chunks.append(text); metadata = getattr(chunk, "usage_metadata", None) or metadata
                yield text
        self._set_usage(_usage_from_metadata(metadata, prompt, "".join(chunks), .0002, .0006))


class GeminiProvider(LLMProvider):
    """Google Gen AI SDK provider, streamed through the shared async interface."""
    def __init__(self, api_key: str, model: str | None = None, client=None):
        if client is None:
            from google import genai
            client = genai.Client(api_key=api_key)
        self.client = client
        self.model = model or settings.GEMINI_MODEL

    async def generate(self, prompt: str, stream: bool = True) -> AsyncIterator[str]:
        chunks, usage_metadata = [], None
        config = {"temperature": settings.TEMPERATURE}
        if stream:
            response_stream = self.client.aio.models.generate_content_stream(
                model=self.model, contents=prompt, config=config
            )
            # google-genai's async client returns an awaitable async iterator.
            # Accept an iterator directly too to keep this adapter stable across
            # compatible SDK revisions and simple test doubles.
            if inspect.isawaitable(response_stream):
                response_stream = await response_stream
            async for chunk in response_stream:
                text = getattr(chunk, "text", None)
                if text:
                    text = str(text)
                    chunks.append(text)
                    yield text
                usage_metadata = getattr(chunk, "usage_metadata", None) or usage_metadata
        else:
            response = await self.client.aio.models.generate_content(
                model=self.model, contents=prompt, config=config
            )
            text = str(getattr(response, "text", "") or "")
            chunks.append(text)
            usage_metadata = getattr(response, "usage_metadata", None)
            yield text
        self._set_usage(_usage_from_metadata(usage_metadata, prompt, "".join(chunks), 0.0, 0.0))


def get_llm_provider() -> LLMProvider:
    requested = settings.LLM_PROVIDER.strip().lower()
    choices = [requested] if requested not in {"", "auto"} else ["openai", "anthropic", "mistral", "gemini"]
    for choice in choices:
        try:
            if choice == "openai" and settings.OPENAI_API_KEY:
                logger.info("Using OpenAI LLM provider")
                return OpenAIProvider(settings.OPENAI_API_KEY)
            if choice == "anthropic" and settings.ANTHROPIC_API_KEY:
                logger.info("Using Anthropic LLM provider")
                return AnthropicProvider(settings.ANTHROPIC_API_KEY)
            if choice == "mistral" and settings.MISTRAL_API_KEY:
                logger.info("Using Mistral LLM provider")
                return MistralProvider(settings.MISTRAL_API_KEY)
            if choice == "gemini" and settings.GEMINI_API_KEY:
                logger.info("Using Gemini LLM provider")
                return GeminiProvider(settings.GEMINI_API_KEY)
        except ImportError:
            logger.warning("%s provider was requested but its optional package is not installed; using stub fallback", choice)
            break
    logger.warning("No usable LLM provider credentials found (LLM_PROVIDER=%s); using offline StubLLM fallback", requested or "auto")
    return StubProvider()
