import logging
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.config import settings
from app.api.routes import api_keys, audit, auth, chat, documents, analytics, evals, feedback, health, me, status, ws, workspaces
from app.core.security import ResilientRateLimiter
from app.core.telemetry import configure_telemetry
from app.core.vector_store import VectorStoreManager
from app.core.rag_pipeline import RAGPipeline
from app.core.graph_agent import RAGGraphAgent
from app.core.llm_provider import llm_runtime_status
from app.core.hybrid_retrieval import embedding_runtime_status, reranker_runtime_status
from app.utils.cache import CacheManager
from app.models.database import init_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting NeuralRAG Enterprise Platform...")
    settings.validate_production_settings()
    logger.info("Provider runtime: LLM: %s", llm_runtime_status())
    logger.info("Provider runtime: embeddings: %s", embedding_runtime_status())
    logger.info("Provider runtime: reranker: %s", reranker_runtime_status())
    await init_db()
    app.state.started_at = time.monotonic()

    vector_store = VectorStoreManager()
    rag_pipeline = RAGPipeline(vector_store)
    graph_agent = RAGGraphAgent(vector_store)
    cache_manager = CacheManager()
    await cache_manager.connect()

    app.state.vector_store = vector_store
    app.state.rag_pipeline = rag_pipeline
    app.state.graph_agent = graph_agent
    app.state.cache = cache_manager
    ws.manager.configure_redis(cache_manager.redis)
    await ws.manager.start()
    app.state.rate_limiter = ResilientRateLimiter(cache_manager.redis, settings.RATE_LIMIT_WINDOW_SECONDS)
    app.state.max_upload_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024

    logger.info("NeuralRAG Platform ready")
    yield
    logger.info("Shutting down...")
    await ws.manager.stop()
    if cache_manager.redis:
        await cache_manager.redis.aclose()

app = FastAPI(title=settings.APP_NAME, version=settings.APP_VERSION, lifespan=lifespan)
configure_telemetry(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)
app.add_middleware(GZipMiddleware)

app.include_router(auth.router, prefix="/api/v1")
app.include_router(api_keys.router, prefix="/api/v1")
app.include_router(audit.router, prefix="/api/v1")
app.include_router(workspaces.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")
app.include_router(documents.router, prefix="/api/v1")
app.include_router(analytics.router, prefix="/api/v1")
app.include_router(evals.router, prefix="/api/v1")
app.include_router(feedback.router, prefix="/api/v1")
app.include_router(me.router, prefix="/api/v1")
app.include_router(health.router, prefix="/api/v1")
app.include_router(ws.router)
app.include_router(status.router)

@app.get("/")
async def root():
    # This deliberately exposes only a boolean.  The frontend needs to know
    # whether to enable the OAuth entry point, but credentials themselves
    # must never be exposed to the browser.
    return {
        "message": "NeuralRAG Enterprise Platform",
        "version": settings.APP_VERSION,
        "docs": "/docs",
        "auth_configured": bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET),
    }
