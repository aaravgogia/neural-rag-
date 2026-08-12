from functools import cached_property
from typing import Optional
from urllib.parse import urlparse

from pydantic_settings import BaseSettings


def async_database_url(database_url: str) -> str:
    """Convert a managed-Postgres URL into SQLAlchemy's asyncpg dialect."""
    if database_url.startswith("postgres://"):
        return "postgresql+asyncpg://" + database_url[len("postgres://"):]
    if database_url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + database_url[len("postgresql://"):]
    return database_url

class Settings(BaseSettings):
    ENVIRONMENT: str = "development"
    APP_NAME: str = "NeuralRAG Enterprise"
    APP_VERSION: str = "2.0.0"
    DEBUG: bool = False
    FRONTEND_URL: str = "http://localhost:3000"

    OPENAI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    MISTRAL_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    # Mistral is the default real-provider choice. Set this to `auto` to
    # retain ordered provider discovery, or select another provider explicitly.
    LLM_PROVIDER: str = "mistral"
    GROQ_API_KEY: Optional[str] = None

    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/api/v1/auth/google/callback"

    # Development has a harmless default. Production refuses to boot unless
    # this value is replaced with a long random secret.
    SECRET_KEY: str = "dev-secret-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24
    OAUTH_STATE_TTL_SECONDS: int = 600
    AUTH_CODE_TTL_SECONDS: int = 60
    COOKIE_SECURE: Optional[bool] = None

    DATABASE_URL: str = "sqlite+aiosqlite:///./neuralrag.db"
    REDIS_URL: str = "redis://localhost:6379"
    INGESTION_QUEUE_ENABLED: bool = True
    WS_REDIS_BROADCAST_ENABLED: bool = True
    PUBLIC_DEMO_MAX_CONNECTIONS: int = 50

    CHROMA_PERSIST_DIR: str = "./chroma_db"
    CHROMA_COLLECTION_NAME: str = "enterprise_docs"
    # `chroma` remains the single-process default. `pgvector` stores vectors
    # in the configured Postgres database for multi-process deployments.
    VECTOR_STORE_PROVIDER: str = "chroma"
    PGVECTOR_TABLE_NAME: str = "vector_embeddings"
    PGVECTOR_DIMENSIONS: int = 1536

    LLM_MODEL: str = "gpt-4o-mini"
    ANTHROPIC_MODEL: str = "claude-3-5-sonnet-latest"
    MISTRAL_MODEL: str = "mistral-small-latest"
    GEMINI_MODEL: str = "gemini-2.5-flash"
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_PROVIDER: str = "sentence_transformers"
    SENTENCE_TRANSFORMER_MODEL: str = "all-MiniLM-L6-v2"
    RERANKER_ENABLED: bool = False
    HYDE_ENABLED: bool = False
    RERANKER_MODEL: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    FREE_MONTHLY_TOKEN_QUOTA: int = 100_000
    FREE_MONTHLY_REQUEST_QUOTA: int = 500
    PRO_MONTHLY_TOKEN_QUOTA: int = 2_000_000
    PRO_MONTHLY_REQUEST_QUOTA: int = 10_000
    # Telemetry remains opt-in: an unset endpoint keeps local/demo startup
    # dependency-free from an observability collector.
    OTEL_EXPORTER_ENDPOINT: str = ""
    OTEL_CONSOLE_EXPORTER: bool = False
    PII_REDACTION_ENABLED: bool = True
    PRESIDIO_SPACY_MODEL: str = "en_core_web_sm"
    MAX_TOKENS: int = 2000
    TEMPERATURE: float = 0.1
    CONVERSATION_HISTORY_MESSAGES: int = 6
    CONVERSATION_HISTORY_TOKEN_BUDGET: int = 1800

    CHUNK_SIZE: int = 1000
    CHUNK_OVERLAP: int = 200
    TOP_K_RESULTS: int = 5
    MAX_UPLOAD_SIZE_MB: int = 20
    ALLOWED_ORIGINS: str = ""
    REQUESTS_PER_MINUTE: int = 60
    AUTHENTICATED_CHAT_REQUESTS_PER_MINUTE: int = 60
    PUBLIC_DEMO_REQUESTS_PER_MINUTE: int = 12
    RATE_LIMIT_WINDOW_SECONDS: int = 60
    RETRIEVAL_CONFIDENCE_THRESHOLD: float = 0.35
    WEB_SEARCH_PROVIDER: str = "auto"
    TAVILY_API_KEY: str = ""
    WEB_SEARCH_MAX_RESULTS: int = 3

    class Config:
        env_file = ".env"

    @cached_property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() == "production"

    @cached_property
    def allowed_origins(self) -> list[str]:
        configured = [origin.strip().rstrip("/") for origin in self.ALLOWED_ORIGINS.split(",") if origin.strip()]
        if self.FRONTEND_URL:
            configured.append(self.FRONTEND_URL.rstrip("/"))
        if not self.is_production:
            configured.extend(["http://localhost:3000", "http://localhost:5173", "http://localhost:4173"])
        return list(dict.fromkeys(configured))

    @cached_property
    def cookie_secure(self) -> bool:
        return self.is_production if self.COOKIE_SECURE is None else self.COOKIE_SECURE

    def validate_production_settings(self) -> None:
        if not self.is_production:
            return
        if self.SECRET_KEY == "dev-secret-change-in-production" or len(self.SECRET_KEY) < 32:
            raise RuntimeError("SECRET_KEY must be a unique random value of at least 32 characters in production")
        requested_provider = self.LLM_PROVIDER.strip().lower() or "auto"
        provider_keys = {
            "openai": self.OPENAI_API_KEY,
            "anthropic": self.ANTHROPIC_API_KEY,
            "mistral": self.MISTRAL_API_KEY,
            "gemini": self.GEMINI_API_KEY,
        }
        if requested_provider == "auto":
            has_llm_key = any(provider_keys.values())
        else:
            has_llm_key = bool(provider_keys.get(requested_provider))
        if not has_llm_key:
            raise RuntimeError(
                "A real API key matching LLM_PROVIDER must be configured in production "
                "(OPENAI_API_KEY, ANTHROPIC_API_KEY, MISTRAL_API_KEY, or GEMINI_API_KEY)"
            )
        if self.VECTOR_STORE_PROVIDER.strip().lower() == "pgvector":
            if not self.DATABASE_URL.startswith("postgresql"):
                raise RuntimeError("VECTOR_STORE_PROVIDER=pgvector requires a PostgreSQL DATABASE_URL")
            if self.EMBEDDING_PROVIDER.strip().lower() not in {"openai", "sentence_transformers", "sentence-transformers", "hashing"}:
                raise RuntimeError("VECTOR_STORE_PROVIDER=pgvector requires openai, sentence_transformers, or hashing embeddings")
        if not self.FRONTEND_URL.startswith("https://"):
            raise RuntimeError("FRONTEND_URL must use HTTPS in production")
        if any(urlparse(origin).scheme != "https" for origin in self.allowed_origins):
            raise RuntimeError("ALLOWED_ORIGINS must contain only HTTPS origins in production")

settings = Settings()
