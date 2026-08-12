# Low-cost deployment: Render + Vercel + Neon + Upstash + Mistral

This is a real, low-traffic deployment path—not an “unlimited free
production” claim. It uses:

| Component | Free service | Role |
| --- | --- | --- |
| API | Render Free Web Service | FastAPI, WebSockets, inline ingestion |
| Frontend | Vercel Hobby | Vite static site |
| Database | Neon Free | Postgres application data and pgvector embeddings |
| Cache / queue features | Upstash Free | Redis-compatible TLS cache, rate limits, and room broadcast |
| LLM | Mistral API | Real Mistral-model answers |

## 1. Create the accounts and values

1. Create a Neon project. Copy its **pooled** connection string and leave its
   TLS query intact, for example:

   ```text
   postgresql://USER:PASSWORD@HOST/neondb?sslmode=require&channel_binding=require
   ```

   The application converts the scheme to SQLAlchemy’s `postgresql+asyncpg`
   form while preserving `sslmode=require`.
2. Create an Upstash Redis database with TLS enabled. Copy its **Redis TCP**
   URL (not the REST URL), which begins `rediss://`. The app uses `redis-py`,
   which accepts `rediss://` directly.
3. Create a Mistral API key. This is server-only: never put
   `MISTRAL_API_KEY` in Vercel or any `VITE_*` variable.
4. Create a Google OAuth web client if you want Google login. You will add the
   redirect URI after Render has assigned the API URL.

## 2. Deploy the backend on Render

Use [render-free.yaml](render-free.yaml) as the Blueprint, not the existing
`render.yaml` demo Blueprint. It runs the full `backend/Dockerfile` and sets:

```text
ENVIRONMENT=production
LLM_PROVIDER=mistral
MISTRAL_MODEL=mistral-small-latest
EMBEDDING_PROVIDER=sentence_transformers
VECTOR_STORE_PROVIDER=pgvector
PGVECTOR_DIMENSIONS=384
INGESTION_QUEUE_ENABLED=false
```

In the Render dashboard, set the Blueprint’s `sync: false` values:

```text
DATABASE_URL=<Neon URL from step 1>
REDIS_URL=<Upstash rediss:// TCP URL from step 1>
MISTRAL_API_KEY=<Mistral API key>
SECRET_KEY=<at least 32 random characters>
FRONTEND_URL=<set after Vercel deployment>
ALLOWED_ORIGINS=<set after Vercel deployment>
GOOGLE_CLIENT_ID=<optional>
GOOGLE_CLIENT_SECRET=<optional>
GOOGLE_REDIRECT_URI=<set after API URL is known>
```

The free path deliberately has no worker. With
`INGESTION_QUEUE_ENABLED=false`, uploads execute inline in the API process and
finish as `done` or `failed`; no document is left queued for a nonexistent ARQ
worker. This makes large uploads slower and subject to the free service’s
request/runtime constraints.

On first boot, the backend's existing idempotent database bootstrap creates
the application tables plus the pgvector extension/table. Its 384-dimension
local sentence-transformer vectors are therefore persistent in Neon, instead
of disappearing with Render’s local filesystem. Teams that prefer managed
migrations can run `alembic upgrade head` separately before deployment.

## 3. Deploy the frontend on Vercel

Import the repository in Vercel and select `frontend` as the Root Directory.
`frontend/vercel.json` already specifies the Vite build, `dist` output, and SPA
rewrite. Set build-time environment values:

```text
VITE_API_URL=https://<your-render-api>.onrender.com
VITE_WS_URL=https://<your-render-api>.onrender.com
```

The frontend converts that HTTPS WebSocket base to `wss://` automatically.
Redeploy after saving the variables.

Copy the Vercel URL (for example `https://your-app.vercel.app`) back to Render:

```text
FRONTEND_URL=https://your-app.vercel.app
ALLOWED_ORIGINS=https://your-app.vercel.app
```

Redeploy Render. These HTTPS URLs satisfy the application’s production safety
validation.

## 4. Enable Google OAuth (optional)

After the Render API exists, add this exact authorized redirect URI in Google
Cloud Console and set `GOOGLE_REDIRECT_URI` to the same value:

```text
https://<your-render-api>.onrender.com/api/v1/auth/google/callback
```

Then redeploy the API. Use exact HTTPS hostnames—no trailing slash and no
localhost variation.

## What free actually costs

- **Render:** a free service sleeps after 15 minutes without inbound traffic.
  Its next request can take roughly a minute to wake. The filesystem is
  ephemeral; do not store uploads, Chroma, or SQLite there as durable data.
  Render can restart free services at any time, so the first request may also
  reload the sentence-transformer model.
- **Neon:** use the current dashboard quota as the source of truth. The common
  free allocation is small (often described as about 0.5 GB); vectors consume
  storage quickly. Watch both data and compute quotas before uploading large
  document collections.
- **Upstash:** the free tier is currently advertised as 256 MB and 500,000
  commands/month. Cache hits, rate limiting, presence, and pub/sub all count
  as commands. If it is unavailable or exhausted, this app starts and falls
  back to per-process cache/rate limits; cross-instance WebSocket broadcasting
  is then unavailable.
- **Mistral:** the API key is billed according to your Mistral account and
  selected model. This means the infrastructure can remain free, but this
  configuration is no longer a genuinely $0 end-to-end stack. Set a usage
  limit in Mistral before launch and treat provider `429` responses as an
  expected capacity boundary, not a deploy bug.
- **No worker:** inline ingestion is correct for a single free API but is not
  suitable for long-running or high-volume uploads. Upgrade to a worker before
  relying on background throughput.

## Final checklist

1. `https://<render-api>/status` returns `{"status":"ok",...}`.
2. Startup logs say `ChatMistralAI (real; LLM_PROVIDER=mistral)`, not StubLLM.
3. Upload a small PDF, wait for `queued → processing → done`, then ask a
   question and verify citations arrive.
4. Confirm Neon contains `vector_embeddings` rows after an upload.
5. Open the Vercel site after a 15+ minute idle period and verify the first
   request recovers from the expected Render cold start.

Current provider facts and limits should be rechecked before public launch:
[Render free-service limits](https://render.com/docs/free),
[Upstash free-tier details](https://upstash.com/blog/upstash-vs-redis-cloud-a-2026-comparison),
and [Neon connection guidance](https://neon.com/docs/connect/connection-errors).
