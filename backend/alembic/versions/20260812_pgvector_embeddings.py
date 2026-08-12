"""Create shared pgvector embedding storage.

Revision ID: 20260812_pgvector_embeddings
Revises: 20260812_initial_application_schema
"""
from alembic import op
import os

revision = "20260812_pgvector_embeddings"
down_revision = "20260812_initial_application_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # HNSW is preferable to IVFFlat here: per-workspace collections are small
    # and continually updated, so it avoids IVFFlat training/list tuning.
    # pgvector is an optional production provider.  Keeping this revision a
    # no-op for SQLite makes `alembic upgrade head` usable in local/demo
    # environments too; PostgreSQL gets the extension, table, and HNSW index.
    if op.get_bind().dialect.name != "postgresql":
        return
    dimensions = int(os.getenv("PGVECTOR_DIMENSIONS", "1536"))
    if dimensions <= 0:
        raise ValueError("PGVECTOR_DIMENSIONS must be positive")
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS vector_embeddings (
            id VARCHAR PRIMARY KEY,
            user_id VARCHAR NOT NULL,
            workspace_id VARCHAR NOT NULL,
            namespace VARCHAR NOT NULL DEFAULT 'default',
            content TEXT NOT NULL,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            embedding vector({dimensions}) NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_vector_embeddings_scope ON vector_embeddings (workspace_id, namespace)")
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_vector_embeddings_hnsw_cosine
        ON vector_embeddings USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TABLE IF EXISTS vector_embeddings")
