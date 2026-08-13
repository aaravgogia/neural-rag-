from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy import Column, String, DateTime, Integer, Text, Boolean, Float, JSON, inspect, text
from datetime import datetime
import uuid

from app.config import async_database_connect_args, async_database_url, settings

engine = create_async_engine(
    async_database_url(settings.DATABASE_URL),
    echo=False,
    connect_args=async_database_connect_args(settings.DATABASE_URL),
)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String, unique=True, nullable=False)
    name = Column(String)
    picture = Column(String)
    google_id = Column(String, unique=True)
    is_active = Column(Boolean, default=True)
    is_premium = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime)
    total_queries = Column(Integer, default=0)
    total_documents = Column(Integer, default=0)
    # There are no workspace roles in this codebase yet; audit access uses
    # this explicit server-managed flag rather than a client-provided claim.
    is_admin = Column(Boolean, default=False, nullable=False)

class ChatSession(Base):
    __tablename__ = "chat_sessions"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False)
    workspace_id = Column(String, nullable=True, index=True)
    title = Column(String, default="New Chat")
    namespace = Column(String, default="default")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    message_count = Column(Integer, default=0)

class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String, nullable=False)
    user_id = Column(String, nullable=False)
    role = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    sources = Column(JSON, default=[])
    processing_time = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow)

class ConversationMemory(Base):
    """Running older-turn summary for a ChatSession (the conversation id)."""
    __tablename__ = "conversation_memories"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id = Column(String, nullable=False, unique=True, index=True)
    summary = Column(Text, nullable=False, default="")
    summarized_message_count = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

class Document(Base):
    __tablename__ = "documents"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False)
    workspace_id = Column(String, nullable=True, index=True)
    filename = Column(String, nullable=False)
    file_size = Column(Integer)
    file_type = Column(String)
    namespace = Column(String, default="default")
    chunks_count = Column(Integer, default=0)
    status = Column(String, default="processing")
    created_at = Column(DateTime, default=datetime.utcnow)
    vector_ids = Column(JSON, default=[])
    version = Column(Integer, nullable=False, default=1)
    parent_document_id = Column(String, nullable=True, index=True)
    stored_path = Column(String, nullable=True)
    ingestion_progress = Column(Integer, nullable=False, default=0)
    ingestion_error = Column(Text, nullable=True)

class AuthCode(Base):
    """One-time OAuth hand-off codes. Tokens are never put in a URL."""
    __tablename__ = "auth_codes"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, index=True)
    code_hash = Column(String, unique=True, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class APIKey(Base):
    """Only a one-way digest of a programmatic credential is persisted."""
    __tablename__ = "api_keys"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False, default="API key")
    key_prefix = Column(String, nullable=False)
    key_hash = Column(String, nullable=False, unique=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_used_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)

class EvalMetric(Base):
    __tablename__ = "eval_metrics"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=True, index=True)
    session_id = Column(String, nullable=False, index=True)
    query_text = Column(Text, nullable=False)
    groundedness = Column(Float, nullable=False, default=0.0)
    retrieval_relevance = Column(Float, nullable=False, default=0.0)
    latency_ms = Column(Float, nullable=False, default=0.0)
    node_timings = Column(JSON, default={})
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    cache_hit = Column(Boolean, default=False, nullable=False)

class Feedback(Base):
    """One current rating per user and assistant answer."""
    __tablename__ = "feedback"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    message_id = Column(String, nullable=False, index=True)
    session_id = Column(String, nullable=False, index=True)
    user_id = Column(String, nullable=False, index=True)
    rating = Column(String, nullable=False)  # up | down
    comment = Column(Text, nullable=True)
    eval_metric_id = Column(String, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

class TokenUsage(Base):
    """One completed model call, kept separate from browser-session auth."""
    __tablename__ = "token_usage"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=True, index=True)
    session_id = Column(String, nullable=False, index=True)
    prompt_tokens = Column(Integer, nullable=False, default=0)
    completion_tokens = Column(Integer, nullable=False, default=0)
    estimated_cost_usd = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

class DocumentRedaction(Base):
    """Original PII is isolated from searchable chunk text and vector metadata."""
    __tablename__ = "document_redactions"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id = Column(String, nullable=False, index=True)
    user_id = Column(String, nullable=False, index=True)
    entity_type = Column(String, nullable=False)
    replacement = Column(String, nullable=False)
    original_value = Column(Text, nullable=False)
    source_page = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, index=True)
    query_text = Column(Text, nullable=False)
    document_ids_used = Column(JSON, default=[])
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

class Workspace(Base):
    __tablename__ = "workspaces"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    owner_id = Column(String, nullable=False, index=True)
    plan = Column(String, nullable=False, default="free")
    # SAML belongs to an organization/workspace, never a global server switch.
    # Metadata may be an IdP metadata XML document or an HTTPS metadata URL.
    saml_idp_metadata = Column(Text, nullable=True)
    saml_sp_entity_id = Column(String, nullable=True)
    saml_acs_url = Column(String, nullable=True)
    saml_default_role = Column(String, nullable=False, default="viewer")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

class WorkspaceMember(Base):
    __tablename__ = "workspace_members"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id = Column(String, nullable=False, index=True)
    user_id = Column(String, nullable=False, index=True)
    role = Column(String, nullable=False, default="viewer")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id = Column(String, nullable=False, index=True)
    chunk_hash = Column(String, nullable=False, index=True)
    vector_id = Column(String, nullable=True)
    source_page = Column(Integer, nullable=True)
    chunk_index = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # This project currently bootstraps schema without Alembic. create_all
        # cannot add columns to an existing users table, so keep this one
        # backwards-compatible security flag migration explicit and idempotent.
        async def ensure_column(table, column, definition):
            existing = await conn.run_sync(lambda sync_conn: {item["name"] for item in inspect(sync_conn).get_columns(table)})
            if column not in existing:
                await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))
        await ensure_column("users", "is_admin", "BOOLEAN NOT NULL DEFAULT FALSE")
        await ensure_column("documents", "workspace_id", "VARCHAR")
        await ensure_column("chat_sessions", "workspace_id", "VARCHAR")
        await ensure_column("workspaces", "plan", "VARCHAR NOT NULL DEFAULT 'free'")
        await ensure_column("workspaces", "saml_idp_metadata", "TEXT")
        await ensure_column("workspaces", "saml_sp_entity_id", "VARCHAR")
        await ensure_column("workspaces", "saml_acs_url", "VARCHAR")
        await ensure_column("workspaces", "saml_default_role", "VARCHAR NOT NULL DEFAULT 'viewer'")
        await ensure_column("documents", "version", "INTEGER NOT NULL DEFAULT 1")
        await ensure_column("documents", "parent_document_id", "VARCHAR")
        await ensure_column("documents", "stored_path", "VARCHAR")
        await ensure_column("documents", "ingestion_progress", "INTEGER NOT NULL DEFAULT 0")
        await ensure_column("documents", "ingestion_error", "TEXT")
        await ensure_column("document_chunks", "source_page", "INTEGER")
        await ensure_column("document_chunks", "chunk_index", "INTEGER")

        # Alembic is available for managed production migrations, while this
        # project also supports its established create_all bootstrap path.
        # Make a compose/local pgvector switch self-contained: the extension,
        # table, and HNSW index appear before VectorStoreManager is used.
        if settings.VECTOR_STORE_PROVIDER.strip().lower() == "pgvector":
            table = settings.PGVECTOR_TABLE_NAME
            if not table.replace("_", "").isalnum():
                raise ValueError("PGVECTOR_TABLE_NAME may contain only letters, numbers, and underscores")
            if not settings.DATABASE_URL.startswith("postgresql"):
                raise RuntimeError("VECTOR_STORE_PROVIDER=pgvector requires a PostgreSQL DATABASE_URL")
            dimensions = int(settings.PGVECTOR_DIMENSIONS)
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.execute(text(f"""
                CREATE TABLE IF NOT EXISTS {table} (
                    id VARCHAR PRIMARY KEY, user_id VARCHAR NOT NULL,
                    workspace_id VARCHAR NOT NULL,
                    namespace VARCHAR NOT NULL DEFAULT 'default',
                    content TEXT NOT NULL,
                    metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                    embedding vector({dimensions}) NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """))
            await conn.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{table}_scope ON {table} (workspace_id, namespace)"))
            await conn.execute(text(f"""
                CREATE INDEX IF NOT EXISTS ix_{table}_hnsw_cosine
                ON {table} USING hnsw (embedding vector_cosine_ops)
                WITH (m = 16, ef_construction = 64)
            """))

        # Backfill one deterministic personal workspace per existing user.
        # Vector metadata cannot be reconstructed from DB alone; legacy vectors
        # remain user-owned until re-uploaded, while all new access is scoped.
        users = (await conn.execute(text("SELECT id FROM users"))).scalars().all()
        for user_id in users:
            workspace_id = f"personal-{user_id}"
            await conn.execute(text("INSERT INTO workspaces (id, name, owner_id, created_at) SELECT :id, :name, :owner_id, CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM workspaces WHERE id = :id)"), {"id": workspace_id, "name": "Personal workspace", "owner_id": user_id})
            await conn.execute(text("INSERT INTO workspace_members (id, workspace_id, user_id, role, created_at) SELECT :member_id, :workspace_id, :user_id, 'owner', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM workspace_members WHERE workspace_id = :workspace_id AND user_id = :user_id)"), {"member_id": str(uuid.uuid4()), "workspace_id": workspace_id, "user_id": user_id})
            await conn.execute(text("UPDATE documents SET workspace_id = :workspace_id WHERE user_id = :user_id AND workspace_id IS NULL"), {"workspace_id": workspace_id, "user_id": user_id})
            await conn.execute(text("UPDATE chat_sessions SET workspace_id = :workspace_id WHERE user_id = :user_id AND workspace_id IS NULL"), {"workspace_id": workspace_id, "user_id": user_id})
