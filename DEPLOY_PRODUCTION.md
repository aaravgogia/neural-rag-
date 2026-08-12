# Deploy NeuralRAG production on Render

`render.yaml` is intentionally the public, zero-credential demo. Use
`render-production.yaml` for the real application: FastAPI, ARQ worker,
Render Postgres with pgvector, Render Key Value (Redis-compatible), and the
Vite static site.

## Before you start

1. Push this repository to GitHub and select the branch you intend to deploy.
2. Create or choose a Mistral API key. This Blueprint uses Mistral for the
   production LLM and local 384-dimension sentence-transformer embeddings in
   pgvector.
3. In Google Cloud Console, create an OAuth **Web application** client. Do not
   set its redirect URI until Render assigns the API URL in step 3.

## 1. Create the Render Blueprint

In Render, select **New > Blueprint**, choose the repository, and select
`render-production.yaml` rather than the default `render.yaml`.

The Blueprint creates these resources in Singapore:

| Resource | Name | Purpose |
| --- | --- | --- |
| Web service | `neuralrag-production-api` | Full `app.main:app` FastAPI application |
| Worker | `neuralrag-production-worker` | ARQ document-ingestion worker |
| Postgres | `neuralrag-production-db` | Application data and shared pgvector embeddings |
| Key Value | `neuralrag-production-redis` | Queue, cache, shared rate limits, and WebSocket fan-out |
| Static site | `neuralrag-production-frontend` | Vite/React frontend served from `frontend/dist` |

Render will prompt for the Blueprint values marked `sync: false`. Enter:

| Variable | Where | Value |
| --- | --- | --- |
| `SECRET_KEY` | API | A fresh random secret of at least 32 characters; for example `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `MISTRAL_API_KEY` | API | Your real Mistral key. The worker securely references this API-service variable. |
| `GOOGLE_CLIENT_ID` | API | Google OAuth web-client ID |
| `GOOGLE_CLIENT_SECRET` | API | Google OAuth web-client secret |
| `GOOGLE_REDIRECT_URI` | API | Leave for step 3 if the API URL is not assigned yet. |

Never set `MISTRAL_API_KEY`, OAuth secrets, or `SECRET_KEY` as `VITE_*`
variables: Vite publishes those values to every browser.

## 2. First deployment and database setup

Deploy the Blueprint. The API image runs `alembic upgrade head` as its
pre-deploy command. The app also performs its established idempotent bootstrap
at startup. On Render Postgres, the migration enables `CREATE EXTENSION vector`
and creates the HNSW-backed pgvector table.

Render injects `DATABASE_URL` and `REDIS_URL` through managed-service links;
do not replace them with copied connection strings. Render’s standard
`postgresql://` URL is converted to `postgresql+asyncpg://` by the app before
SQLAlchemy opens a connection.

Wait until all of these are healthy:

```text
neuralrag-production-api      Live
neuralrag-production-worker   Live
neuralrag-production-db       Available
neuralrag-production-redis    Available
```

Open `https://<your-api>.onrender.com/status`. It must return JSON with
`"status": "ok"`. The API startup log should report **ChatMistralAI (real)** and
**SentenceTransformer (real)**, not a StubLLM or hashing fallback.

## 3. Connect frontend and Google OAuth

Render assigns both the API and static site HTTPS URLs. Blueprint service links
set `FRONTEND_URL`/`ALLOWED_ORIGINS` on the API and inject the API URL into
`VITE_API_URL` and `VITE_WS_URL` at frontend build time. `VITE_WS_URL` receives
the same HTTPS URL and the frontend converts it to `wss://` before opening the
browser WebSocket.

Service-link values refresh on Blueprint sync, not instantly when a URL changes.
After both public URLs exist, run one manual deploy of the API and then one of
the static site. This order ensures the frontend bundle has the live API URL.

Now set the Google Cloud Console authorized redirect URI exactly to:

```text
https://<your-api>.onrender.com/api/v1/auth/google/callback
```

Set the same value as the API service’s `GOOGLE_REDIRECT_URI`, save it, and
redeploy the API. Google rejects even small variations such as `http`, a
trailing slash, or a different hostname.

## 4. Custom domains

1. In Render, attach `api.example.com` to `neuralrag-production-api` and
   `app.example.com` to `neuralrag-production-frontend`.
2. Add the DNS records Render displays and wait for TLS verification.
3. Update the API’s `FRONTEND_URL` and `ALLOWED_ORIGINS` to
   `https://app.example.com`, then redeploy the API.
4. Set the frontend’s build-time `VITE_API_URL=https://api.example.com` and
   `VITE_WS_URL=wss://api.example.com`, then rebuild/redeploy the static site.
5. Change Google’s redirect URI and `GOOGLE_REDIRECT_URI` to
   `https://api.example.com/api/v1/auth/google/callback`.

The current production validation deliberately requires a 32+ character
`SECRET_KEY`, HTTPS `FRONTEND_URL`, and HTTPS-only `ALLOWED_ORIGINS`. Render
`onrender.com` URLs and verified custom domains satisfy those checks; raw
private service URLs and `http://localhost` do not.

## PII redaction prerequisite

`PII_REDACTION_ENABLED=true` is enabled by the production Blueprint. The full
[backend Dockerfile](backend/Dockerfile) now runs
`python -m spacy download en_core_web_sm`, so Presidio has its NER model in a
fresh production image. Do not use `Dockerfile.demo` for this path: the demo
intentionally omits the heavyweight Presidio/spaCy dependencies.

## Final smoke test

1. Sign in through Google.
2. Upload a small PDF and confirm its status transitions `queued` →
   `processing` → `done`.
3. Ask a chat question and confirm streamed tokens and citations arrive over
   `wss://`.
4. Check `/status` and the Render worker logs for Redis/ARQ connectivity.
5. Run `alembic current` from the API Shell; it should show
   `20260812_pgvector_embeddings (head)`.

Keep `render.yaml` and `backend/railway.json` for the independently deployable
demo path. They do not receive production secrets or share this production
database.
