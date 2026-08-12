# Production deployment checklist

This app starts in a safe demo mode when optional services are absent. At boot,
look for the three `Provider runtime:` log entries: they state the selected LLM,
dense embedding backend, and reranker state without revealing credentials.

## Required for a real deployment

| Setting | Real-deployment value | If unset |
| --- | --- | --- |
| `ENVIRONMENT` | `production` | Development safeguards remain active. |
| `SECRET_KEY` | Unique random value, at least 32 characters | Production refuses to start. |
| `FRONTEND_URL` | Public HTTPS frontend URL | Production refuses to start if it is not HTTPS. |
| `ALLOWED_ORIGINS` | Comma-separated HTTPS frontend origins | Only `FRONTEND_URL` is allowed; browser requests from other origins fail CORS. |
| `DATABASE_URL` | Postgres async URL, e.g. `postgresql+asyncpg://...` | SQLite is used locally; it is not suitable for multi-instance production. |
| `REDIS_URL` | Reachable Redis URL | Cache, rate limiting, and queued ingestion degrade to local/in-memory behavior where supported. |

## LLM generation

Set `LLM_PROVIDER` to `openai`, `anthropic`, `mistral`, `gemini`, or `auto`.

| Provider | Required secret | Optional model setting | If missing or SDK unavailable |
| --- | --- | --- | --- |
| OpenAI | `OPENAI_API_KEY` | `LLM_MODEL` | `StubLLM` is used outside production; production refuses to boot if this provider is selected. |
| Anthropic | `ANTHROPIC_API_KEY` | `ANTHROPIC_MODEL` | Same behavior. |
| Mistral | `MISTRAL_API_KEY` | `MISTRAL_MODEL` | Same behavior. |
| Gemini | `GEMINI_API_KEY` | `GEMINI_MODEL` (default `gemini-2.5-flash`) | Uses Google’s current `google-genai` SDK. Gemini free-tier access is real but quota- and account-dependent; use it for low traffic, not as a concurrency guarantee. |
| `auto` | Any one of the four above | Provider-specific setting | Tries OpenAI, then Anthropic, Mistral, then Gemini; otherwise uses `StubLLM` outside production. |

`StubLLM` streams deterministic extractive/demo responses. It is not a real
model call. A provider being marked “real” at startup confirms configuration
and installed SDKs; failed API calls remain visible request errors rather than
being silently converted into fake answers.

## Retrieval and optional reranking

| Setting | Recommended value | If unset or unusable |
| --- | --- | --- |
| `EMBEDDING_PROVIDER` | `sentence_transformers` or `openai` | Defaults to local sentence transformers. Unsupported/missing dependencies fall back to `HashingVectorizer` with a warning. |
| `SENTENCE_TRANSFORMER_MODEL` | `all-MiniLM-L6-v2` | Default model is used. |
| `OPENAI_API_KEY` with `EMBEDDING_PROVIDER=openai` | Valid key | Embeddings fall back to hashing if absent or the embedding call fails. |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | Default model is used for OpenAI embeddings. |
| `RERANKER_ENABLED` | `true` for pro workspaces only | Cross-encoder is skipped. |
| `RERANKER_MODEL` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | Default model is used. Failures preserve MMR ordering. |

The initial Hugging Face downloads are approximately 80–100 MB for
`all-MiniLM-L6-v2` and 80–100 MB for the MiniLM cross-encoder, plus framework
and tokenizer files. Models are loaded on first dense-index construction. The
current WebSocket demo agent constructs an index during application import, so
that first load can occur at process startup rather than the first chat. Expect
seconds to minutes on a cold network/cache and roughly 0.1–0.3 GB RAM per
loaded model depending on PyTorch/platform. Pre-bake/cache model artifacts in
the production image or use a persistent model cache to avoid cold-start
latency.

### Shared pgvector storage (optional)

Set `VECTOR_STORE_PROVIDER=pgvector` to replace the default local Chroma
store. This requires PostgreSQL 15+ (or a managed Postgres service) with the
`pgvector` extension available to the application database user, a real
`OPENAI_API_KEY` with a 1536-dimension model such as `text-embedding-3-small`,
or local `sentence_transformers` with a matching 384-dimension
`PGVECTOR_DIMENSIONS`. Apply
`backend/alembic/versions/20260812_pgvector_embeddings.py` before starting
application workers, then run `backend/scripts/migrate_chroma_to_pgvector.py`
once if data already exists in Chroma. The migration uses an HNSW cosine index:
it is immediately useful for small, incrementally-updated workspace corpora;
it trades more memory/build work for better online-insert behavior than IVFFlat.
The supplied `docker-compose.yml` now uses the pgvector PostgreSQL 16 image;
set `VECTOR_STORE_PROVIDER=pgvector` in `.env`, then run
`docker compose up --build`. The normal application bootstrap creates the
extension/table/index for this local compose path. Confirm a real deployment
with `cd backend && python scripts/pgvector_smoke.py` after setting its real
database URL and embedding key.

## Authentication and optional integrations

| Setting | If unset |
| --- | --- |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI` | Google OAuth cannot complete; use another supported authentication path. |
| `TAVILY_API_KEY` with `WEB_SEARCH_PROVIDER=tavily` | Low-confidence web-search fallback is skipped cleanly. |
| `OTEL_EXPORTER_ENDPOINT` | Telemetry uses console/no-op behavior; no OTLP export occurs. |
| `PII_REDACTION_ENABLED` | Defaults to enabled in full production requirements. If Presidio/spaCy/model loading fails, ingestion logs the condition and follows its configured graceful fallback. |

### Workspace SAML SSO (optional)

The full backend requirements install `python3-saml`. Configure each enterprise
workspace in the database/admin workflow with `saml_idp_metadata` (IdP metadata
XML or an HTTPS metadata URL), `saml_sp_entity_id`, and `saml_acs_url`. Optional
`saml_default_role` may be `viewer` (default) or `editor`; JIT-provisioned users
are added to that workspace only. The login and assertion-consumer endpoints are:

```text
GET  /api/v1/auth/saml/{workspace_id}/login
POST /api/v1/auth/saml/{workspace_id}/acs
```

They create the same one-time authorization code used by Google OAuth, and the
existing `/api/v1/auth/exchange` endpoint issues the normal JWT. SAML is not
configured globally, and API-key authentication is unaffected. An unconfigured
workspace returns HTTP 503 rather than redirecting to a broken IdP flow.

## Pre-flight commands

```bash
pip install -r backend/requirements.txt
python -m spacy download en_core_web_sm
cd backend && uvicorn app.main:app --host 0.0.0.0 --port 8000
```

On startup, verify logs report a real LLM and real embedding backend before
accepting production traffic. Do not place API keys in source control or the
frontend `VITE_` environment variables.
