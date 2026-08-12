"""
Standalone demo entrypoint. Runs the parts that need zero paid external
services (no OpenAI key, no managed Postgres/Redis) -- hybrid retrieval,
the observable LangGraph agent, WebSocket streaming, AND real Google auth
backed by SQLite.

Auth is included here because it's genuinely cheap: it only needs
SQLAlchemy + python-jose + httpx, none of which touch langchain/chromadb.
The one thing this can't do without YOUR credentials is the actual Google
OAuth handshake -- see DEPLOYMENT.md for the 5-minute Google Cloud Console
setup. Until then, /auth/google/login returns a clear 503 instead of
silently failing.

The full main.py (real vector store, real LLM, Postgres/Redis) is
unchanged and still the production entrypoint once you have those
credentials too.
"""
import logging
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.api.routes import ws, auth, status
from app.core.security import ResilientRateLimiter
from app.models.database import init_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()  # creates neuralrag.db + tables on first boot, no-op after
    app.state.started_at = time.monotonic()
    app.state.rate_limiter = ResilientRateLimiter(window_seconds=settings.RATE_LIMIT_WINDOW_SECONDS)
    # Demo intentionally has no Redis; make its local-only behavior explicit.
    ws.manager.configure_redis(None)
    logger.info("NeuralRAG demo backend ready (SQLite + zero-credential retrieval/agent)")
    yield


app = FastAPI(title="NeuralRAG Demo", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False, allow_methods=["GET", "POST"], allow_headers=["Content-Type", "Authorization"],
)
app.include_router(ws.router)
app.include_router(auth.router, prefix="/api/v1")
app.include_router(status.router)


@app.get("/")
async def root():
    return {
        "status": "ok",
        "websocket": "/ws/chat/{session_id}",
        "auth_configured": bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET),
    }
