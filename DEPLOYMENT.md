# Deploying this project

## Production security checklist (required)

Before exposing the full backend, configure these server-side variables:

```text
ENVIRONMENT=production
SECRET_KEY=<a unique random value, at least 32 characters>
OPENAI_API_KEY=<your key>
DATABASE_URL=<managed Postgres asyncpg URL>
REDIS_URL=<managed Redis URL>
FRONTEND_URL=https://your-frontend.example
ALLOWED_ORIGINS=https://your-frontend.example
GOOGLE_CLIENT_ID=<your client ID>
GOOGLE_CLIENT_SECRET=<your client secret>
GOOGLE_REDIRECT_URI=https://your-api.example/api/v1/auth/google/callback
```

Set `VITE_API_URL=https://your-api.example` and `VITE_WS_URL=wss://your-api.example` **when the frontend builds**. Do not put server secrets in `VITE_` variables. The full backend will refuse to start in production with the default `SECRET_KEY`, a missing OpenAI key, or non-HTTPS browser origins.

The public demo is intentionally limited to its built-in sample documents. Set both `FRONTEND_URL` and `ALLOWED_ORIGINS` on its host after deploying the frontend; its WebSocket rejects every other origin and is rate-limited.

Two independent pieces, deployed separately:

1. **Frontend** (static site) → Vercel or Netlify
2. **Demo backend** (`app.main_demo:app`) → Render or Railway — zero external
   credentials required, this is what powers the "Run it live" button

The full production backend (`app.main:app`, with real auth/DB/LLM) needs
your own OpenAI + Google OAuth + Postgres + Redis credentials and is
documented separately at the bottom — it is **not** required for the live
demo to work.

---

## 0. Google OAuth setup (needed before auth will work anywhere)

Both the demo backend and the full backend need real Google OAuth
credentials — without them, the login page correctly shows "Google
sign-in isn't configured" instead of a broken redirect (verified: the
`/` endpoint reports `auth_configured: false/true` and the frontend checks
it before showing the button as usable).

**5-minute setup:**

1. [Google Cloud Console](https://console.cloud.google.com/apis/credentials) → Create Project (or select existing)
2. **APIs & Services → OAuth consent screen** → External → fill in app name/email → Save
3. **APIs & Services → Credentials** → Create Credentials → OAuth client ID → Web application
4. Add an **Authorized redirect URI**:
   - Local dev: `http://localhost:8000/api/v1/auth/google/callback`
   - Production: `https://YOUR-BACKEND-URL.onrender.com/api/v1/auth/google/callback`
5. Copy the generated **Client ID** and **Client Secret**
6. Set them as environment variables on your backend deployment:
   ```
   GOOGLE_CLIENT_ID=xxxxx.apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=xxxxx
   GOOGLE_REDIRECT_URI=https://YOUR-BACKEND-URL.onrender.com/api/v1/auth/google/callback
   FRONTEND_URL=https://YOUR-FRONTEND-URL.vercel.app
   ```

The demo backend (`app.main_demo:app`) stores users in SQLite — no
separate database service needed. Verified end-to-end in this project's
own tests: real user creation, JWT issuance/validation, re-login dedup
(same Google account doesn't create duplicate users), and tampered-token
rejection — see `EXTRAORDINARY_FEATURES.md`.

---

## 1. Deploy the demo backend first (you need its URL for the frontend)

**Fastest local path — one command, no cloud account needed:**

```bash
docker compose -f docker-compose.demo.yml up --build
# Frontend: http://localhost:4173/live-demo
# Backend:  http://localhost:8000
```

This builds `backend/Dockerfile.demo` (the same minimal, zero-credential
image verified end-to-end in this project's test suite) and a dev-mode
frontend container together. Good for trying everything locally; for an
actual public URL a recruiter can open, use Option A or B below instead.

**Option A — Render (recommended for a real deploy, free tier, has a `render.yaml` blueprint):**

1. Push this repo to GitHub
2. On [render.com](https://render.com): New → Blueprint → select the repo
3. Render reads `render.yaml` automatically and builds `backend/Dockerfile.demo`
4. Wait for the build — no environment variables are required
5. Copy the resulting URL, e.g. `https://neuralrag-demo-backend.onrender.com`

**Option B — Railway:**

```bash
cd backend
railway init
railway up
# railway.json in this folder tells it to build Dockerfile.demo
```

**Verify it's actually working before moving on:**

```bash
curl https://YOUR-BACKEND-URL.onrender.com/
# should return: {"status":"ok","websocket":"/ws/chat/{session_id}"}
```

This is the exact same image verified in this project's own test suite —
see `EXTRAORDINARY_FEATURES.md` for the real subprocess-managed end-to-end
test that boots this precise Docker image (clean venv, only
`requirements-demo.txt`) and proves multi-client WebSocket collaboration
actually works, not just that the container starts.

---

## 2. Deploy the frontend, pointed at that backend

**This is the step that's easy to get wrong** — see the note below on why.

**Option A — Vercel:**

1. Push to GitHub, import the repo on [vercel.com](https://vercel.com)
2. Set the root directory to `frontend/`
3. Vercel auto-detects `vercel.json` (build command + SPA rewrites already configured)
4. **Before deploying**, add these two Environment Variables in the Vercel
   project settings (Build & Development, not Runtime — see note below):
   - `VITE_API_URL` = `https://YOUR-BACKEND-URL.onrender.com`
   - `VITE_WS_URL` = `wss://YOUR-BACKEND-URL.onrender.com` (note: `wss://`, not `https://`)
5. Deploy

**Option B — Netlify:**

Same idea — `netlify.toml` is already configured with the build command and
SPA redirect. Set `VITE_API_URL` and `VITE_WS_URL` as build environment
variables in the Netlify UI before deploying.

### Why this step is easy to get wrong (a bug I actually found and fixed)

This is a Vite project. Vite does **not** read `process.env.REACT_APP_*` at
runtime the way Create React App does — it only exposes variables prefixed
`VITE_` via `import.meta.env`, and it substitutes them **at build time**,
not runtime. Earlier in this project, every API call used the CRA-style
`process.env.REACT_APP_API_URL`, which silently constant-folded to the
`localhost:8000` fallback on every build, with no error — meaning setting
`REACT_APP_API_URL` in a hosting provider's dashboard would have had zero
effect. This was found by directly inspecting the built JS bundle, fixed by
migrating every reference to `import.meta.env.VITE_API_URL` /
`import.meta.env.VITE_WS_URL`, and re-verified by grepping the rebuilt
bundle for a real deployed URL to confirm it actually gets baked in.

**Practical implication:** these are build-time values. If you change the
backend URL later, you must rebuild and redeploy the frontend — there is no
runtime config file being read.

---

## 3. Local development (no deployment)

```bash
# Terminal 1 -- demo backend
cd backend
pip install -r requirements-demo.txt
python3 -m uvicorn app.main_demo:app --reload --port 8000

# Terminal 2 -- frontend
cd frontend
npm install
npm run dev
# visit http://localhost:5173 (or whatever port Vite prints)
```

No `.env` needed locally — both `VITE_API_URL` and `VITE_WS_URL` default to
`localhost:8000`.

---

## 4. Full production backend (optional, needs real credentials)

`app.main:app` (not `main_demo:app`) is the full backend with Google OAuth,
Postgres persistence, Redis caching, and real LangChain/OpenAI calls. It
needs:

```
OPENAI_API_KEY, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET,
DATABASE_URL (Postgres), REDIS_URL
```

```bash
cp .env.example .env   # fill in real credentials
docker-compose up --build
```

`docker-compose.yml` in the repo root spins up Postgres + Redis + the full
backend + frontend together. This is the path for an actually-functioning
production deployment with a real LLM instead of the extractive stub —
deploy `backend/Dockerfile` (not `Dockerfile.demo`) to Render/Railway/Fly.io
with those environment variables set, and point the frontend's `VITE_API_URL`
at it instead.
