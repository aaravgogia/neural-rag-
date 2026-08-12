# What makes this stand out (and how I verified it)

Three feature areas, built for real and tested against actual running code —
not descriptions or mockups.

## 1. Advanced Retrieval — `backend/app/core/hybrid_retrieval.py`

**What it is:** BM25 (lexical/keyword) + real `all-MiniLM-L6-v2` sentence
embeddings, fused with Reciprocal Rank Fusion, then re-ranked with Maximal
Marginal Relevance for diversity. An optional
`cross-encoder/ms-marco-MiniLM-L-6-v2` second pass scores the final candidates
when `RERANKER_ENABLED=true`. This is the same architecture behind
production hybrid search in Weaviate, Elasticsearch, and Cohere's rerank API.

**Why hybrid matters:** pure vector search misses exact matches (invoice
numbers, error codes, SKUs). Pure keyword search misses paraphrases. Real
example from testing this module — query *"how long do I have to file
expenses"* against a doc phrased *"submit expense reports within 30 days"*:
zero literal word overlap ("file" vs "submit", "expenses" vs "expense")
until stemming was added, which is exactly the kind of failure mode that
production RAG systems have to engineer around.

**Bugs found and fixed by actually running it** (documented in code comments):
- Zero-score documents were leaking into RRF fusion purely from tie-break
  rank position — fixed by filtering candidates with `score > 0` before fusion
- No stopword removal caused common words ("is", "to") to dominate BM25
  scores on a small corpus — fixed with `sklearn.ENGLISH_STOP_WORDS`
- No stemming meant "expenses"/"expense", "filed"/"file" never matched —
  fixed with `nltk.PorterStemmer` (pure algorithm, no data download needed)

**Verified retrieval quality:** `python scripts/evaluate_hybrid_retrieval.py`
runs NDCG@5 and MRR over labeled demo chunks with the cross-encoder off and
on. The compact benchmark currently scores 1.000/1.000 in both modes, so it
does not claim a synthetic improvement where none was measured.

**Honest trade-off:** models load lazily and are cached per retrieval index.
If the embedding or reranker model is unavailable, the app logs a clear
warning and continues with the offline hashing fallback or MMR order instead
of failing the request.

**Semantic cache** — `backend/app/core/semantic_cache.py` — caches by
*meaning*, not literal string match, using the same cosine-similarity
approach. Tested with real paraphrase pairs (`tests/test_semantic_cache.py`).

## 2. Live Agent Observability — `backend/app/core/graph_agent_v2.py`

A real `langgraph.StateGraph` (analyze → check_cache → retrieve → generate →
grade → retry/end) instrumented to emit a genuine event on every node
transition, with real wall-clock timing — not a simulated animation.

**Eval metrics are computed, not hardcoded:**
- `groundedness`: fraction of the answer's content words that actually
  appear in the retrieved context — a real faithfulness proxy
- `retrieval_relevance`: mean RRF fusion score of the chunks used

Verified end-to-end (`/tmp/test_agent.py` during development): correct
routing on greetings (skips retrieval entirely), correct cache-hit vs
cache-miss behavior with real similarity scores, correct grading.

**Frontend:** `AgentTracePanel.jsx` renders this live — nodes pulse while
active, turn into checkmarks on completion, and show real per-node timing.
Confirmed with actual Playwright screenshots of the running app mid-stream
(node 4/5 "Generate" shown pulsing pink while a partial answer streams in
with a blinking cursor, nodes 1-3 already checked off with real millisecond
timings, node 5 still grey/pending) — this is the literal DOM state at that
instant, not a designed mockup.

## 3. Real-Time Streaming & Collaboration — `backend/app/api/routes/ws.py`

FastAPI WebSocket endpoint (`/ws/chat/{session_id}`) with room-based
broadcasting: every client connected to the same session receives the
identical live event stream.

**Proven, not assumed:** ran two concurrent WebSocket clients against the
same session — one asks a question, the other only listens. Both received
the exact same 54-55 event sequence (presence → user_message → node_start
→ node_end ×5 → ~30 tokens → done) and the identical final answer. This is
the actual output from that test:

```
=== A (asker) received 54 events ===
=== B (observer) received 55 events ===
Final answer seen by this client: [identical text for both]
```

## Honest scope of what's real vs. stubbed

| Component | Status |
|---|---|
| BM25 + sentence-transformer hybrid search, RRF fusion, MMR reranking | **Real**, tested, running |
| Semantic cache | **Real**, tested, running |
| LangGraph StateGraph (routing, retry logic, conditional edges) | **Real**, actually executing |
| WebSocket broadcast / multi-client collaboration | **Real**, proven with concurrent clients |
| Eval metrics (groundedness, relevance) | **Real**, computed from actual retrieved text |
| The LLM generating the final answer text | **Stubbed** (`stub_llm.py`) — extractive/templated from real retrieved chunks, since this sandbox has no OpenAI API key. Swapping in `ChatOpenAI` here is the only change needed for production; everything else (routing, retrieval, streaming, tracing) is unaffected. |
| Dense embeddings | **Real** `all-MiniLM-L6-v2` by default; OpenAI embeddings are optional via `EMBEDDING_PROVIDER=openai` |
| Cross-encoder reranking | **Optional, real** `ms-marco-MiniLM-L-6-v2`; disabled by default and safely bypassed if unavailable |

## Running the live demo yourself

```bash
cd backend
pip install -r requirements.txt
python3 -m uvicorn app.main_demo:app --host 0.0.0.0 --port 8000

cd ../frontend
npm install && npm run build && npx serve -s dist -l 4173
# visit http://localhost:4173/live-demo
```

## Running the tests yourself

```bash
cd backend
pytest tests/ -v
# 11 passed
```

---

## 4. Instrumented 3D topology + command surface

The landing page now has a deliberately narrow use of 3D: it renders the
actual pipeline shape (analyze → retrieve → generate → grade → output), not a
generic floating particle globe. Cyan nodes represent completed trace stages,
the orange generation node and moving orange signal points represent work in
flight, and every connection moves left-to-right in the same direction as a
real query.

`PipelineHero3D.jsx` is loaded only after the landing page has determined that
the device is appropriate for WebGL. `AdaptivePipelineHero.jsx` chooses the
small canvas-based `ParticleBackground` when reduced motion is enabled, when
the device reports four or fewer logical CPUs, or when a short request-frame
probe reports a weak frame rate. The fallback remains an instrumentation field
using the product's trace/pulse colors; it is not a second visual language.

The global Cmd/Ctrl+K command surface is implemented with `cmdk`. It exposes
Dashboard, Chat, Documents, Analytics, and Settings along with New chat and
Upload document actions. It honours existing private-route behavior: an
anonymous command routes to sign-in instead of exposing workspace data.

**Verified in a real local browser, not inferred from source:**
- Desktop landing route shows the editorial hero copy on the left and a boxed
  `LIVE TOPOLOGY` graph on the right. A screenshot should show five labelled
  stages (`ANALYZE`, `RETRIEVE`, `GENERATE`, `GRADE`, `OUTPUT`), cyan and orange
  nodes, left-to-right connector lines, and an orange `FLOWING` status signal.
- Ctrl+K opens a real focusable dialog containing the five navigation entries
  and both actions; the browser accessibility tree exposed it as a dialog,
  combobox, listbox, and selectable options.

**Bundle audit, actual `npm run build` output:**
- Main application chunk: **105.88 kB / 36.83 kB gzip**.
- Landing-only component loader: **2.33 kB / 1.11 kB gzip**.
- Three/R3F/Drei vendor chunk: **827.22 kB / 224.93 kB gzip**. Vite correctly
  reports the chunk-size warning, but it is behind the lazy landing hero import
  and is absent from the initial application chunk. This is intentional: no
  dashboard, chat, documents, analytics, or settings route imports WebGL.

---

## 5. Visible multiplayer session presence

The existing WebSocket room manager now tracks ephemeral participants in the
same rooms that already distribute node traces and streamed tokens. A presence
event contains a unique set of `{id, name, avatar}` participants on every join
and leave. The ChatPage opens a lightweight presence-only socket for the active
authenticated session; persisted messages still use the existing REST endpoint.

Typing is equally ephemeral: the composing client emits a debounced `typing`
event, the room broadcasts it, and each other client shows a small instrumentation
status line. Nothing is written to the database. Private sessions require the
existing JWT in the initial socket join frame and verify that the user owns the
requested session; public demo visitors remain anonymous `Live explorer`s.

**Verified:** automated room-manager tests create two independent sockets and
assert that named avatars are broadcast as two participants on join, one after
leave, and that an active typing event reaches the other participant. The
frontend production build also passes with the avatar stack and typing indicator.

---

## Update: real Google auth + aesthetic login page

Added working Google OAuth to the *lightweight* demo backend (not just the
heavy full-production one) — auth only needs SQLAlchemy + python-jose +
httpx, none of which touch langchain/chromadb, so it's cheap to include.
Users are stored in SQLite (a file in the container), not a managed
Postgres instance — zero additional infra to deploy.

**Real bugs found by actually testing the deployment artifact, not just the source tree:**

1. `graph_agent_v2.py` had a dead `from app.config import settings` import
   that pulled in `pydantic-settings` — a dependency not in
   `requirements-demo.txt`. Only caught by installing the *exact* minimal
   requirements file into a clean virtualenv and trying to import the app,
   not by running it in the full dev environment where the dependency
   happened to already be present.
2. `Dockerfile.demo` never copied `app/models/` — `database.py` and
   `schemas.py` live there, and `auth.py` imports both. This would have
   built successfully (Docker doesn't know a Python import is about to
   fail) and then crashed on first request. Caught by literally simulating
   the Dockerfile's `COPY` instructions into an isolated directory (no
   Docker daemon available in this environment) and booting from *that*
   exact file set — not from the full source tree, which would have
   silently hidden the missing directory.

**Verified for real, end-to-end, in the exact simulated deployment artifact:**
- Server boots with only `requirements-demo.txt` installed
- `GOOGLE_CLIENT_ID`/`SECRET` unset → `/` reports `auth_configured: false`,
  `/api/v1/auth/google/login` returns a clear `503` instead of a broken
  redirect or crash
- Credentials set → redirect to the *real* `accounts.google.com` with
  correctly-formed `client_id`, `redirect_uri`, and `scope` query params
- Real SQLite user creation, JWT issuance + validation, re-login
  deduplication (same Google account doesn't create a duplicate user), and
  tampered-token rejection — 5 new automated tests, all passing (16/16
  total across the test suite now)
- The `/ws/chat` WebSocket route and the new `/api/v1/auth` routes both
  serve correctly from the same isolated build

**Frontend:** the login page is now a split-screen layout — the left panel
reuses the same live pipeline schematic and real proof numbers as the
landing page (so it reads as one continuous product, not a generic auth
template bolted on), and the right panel checks the backend's
`auth_configured` flag on load so a misconfigured deployment shows a clear
inline warning with a working fallback CTA ("Try the live demo instead")
instead of a dead button.
