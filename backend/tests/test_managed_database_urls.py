import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.config import async_database_url


def test_neon_ssl_connection_url_preserves_tls_query_parameters():
    neon_url = "postgresql://user:password@ep-demo.neon.tech/neondb?sslmode=require&channel_binding=require"
    converted = async_database_url(neon_url)

    assert converted.startswith("postgresql+asyncpg://")
    assert "sslmode=require" in converted
    assert "channel_binding=require" in converted
