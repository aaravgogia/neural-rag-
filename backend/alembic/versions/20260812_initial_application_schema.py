"""Create the application schema for Alembic-managed installations.

Revision ID: 20260812_initial_application_schema
Revises: None

The project historically bootstrapped the same metadata in ``init_db``.  This
baseline lets a fresh production database be initialized by ``alembic upgrade
head`` while preserving that bootstrap path for the zero-config demo.
"""
from alembic import op

from app.models.database import Base


revision = "20260812_initial_application_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLAlchemy's metadata is the single schema source of truth in this
    # project. checkfirst makes the baseline safe for an existing database
    # that was previously created by init_db; stamp it after verification.
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind(), checkfirst=True)
