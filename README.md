# Recall

Voice-first learning companion (single user, local-first). The full spec and phase plan is in
[CLAUDE.md](CLAUDE.md); deviations are logged in [DECISIONS.md](DECISIONS.md).

## Status

| Phase | State |
|---|---|
| 0 Skeleton | done |
| 1 Capture to notes | done (fakes verified; real voice/LLM keys untested) |
| 2 Diagrams and memory map | done (verified with fakes) |
| 2.5 Hosted backend + installable PWA | built; tested locally, not yet on a real VM or iOS device |
| 3 Recall engine | done (verified with fakes only) |
| 4 Ingestion and n8n | done (fake LLM; real extraction quality unmeasured) |

## Use it on laptop, iPhone and iPad

Run one always-on copy on a cloud VM and open it from every device: see [DEPLOY.md](DEPLOY.md).

## Run locally

```bash
make dev        # copies .env.example to .env if missing, then docker compose up --build
```

| Service | URL |
|---|---|
| Frontend | http://localhost:3000 |
| Backend / OpenAPI docs | http://localhost:8000/docs |
| n8n | http://localhost:5678 |
| Postgres | 127.0.0.1:5433 |

## Develop

```bash
make install    # uv sync + npm install
make migrate    # alembic upgrade head (needs the db container running)
make test       # backend pytest (needs db) + frontend vitest
make lint       # ruff, mypy, eslint, tsc
make gen-api    # regenerate frontend/lib/api-types.ts from FastAPI's OpenAPI schema
make e2e        # Playwright smoke test (needs `make dev` and `npx playwright install chromium`)
```

## Phase 0 demo

1. `make dev`, wait for the backend log line `Application startup complete`.
2. `curl localhost:8000/healthz` returns `{"status":"ok","db":"up","voice_provider":"fake"}`.
3. Open http://localhost:3000, confirm the header says **Connected**, type a message, press Enter.
4. You see your message and the fake assistant's reply in the transcript.
5. Confirm it is stored: open the session id shown top-right at
   `http://localhost:8000/api/sessions/<session id>`; both utterances are listed.

## Phase 1: turning on real voice

Everything works typed with the fakes. For real speech and note extraction, set these in `.env`
and restart (`docker compose up -d --build backend`):

```bash
VOICE_PROVIDER=pipeline
DEEPGRAM_API_KEY=...
ELEVENLABS_API_KEY=...
ELEVENLABS_VOICE_ID=...
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=...        # LLM_FAST_MODEL / LLM_DEEP_MODEL are preset in .env.example
EMBEDDING_PROVIDER=voyage
EMBEDDING_API_KEY=...
```

Then on http://localhost:3000/session use **Open mic** (use headphones) or hold **Hold to talk**.
The Debug panel shows speech end to first audio for each turn; the target is under 800 ms.

## Phase 1 demo (works with no keys)

1. `make dev`, open http://localhost:3000/session.
2. Type: `RAG retrieves relevant documents before generation. Chunk size trades recall against precision.`
   Two atomic notes appear on the right, marked **New note**.
3. Type `RAG retrieves relevant documents before generation.` again. No duplicate: the note shows
   **Merged into existing note** with a **Show previous** toggle.
4. Click **Undo** on either to revert it. Reload the page: remaining notes persist.

## Phase 2 demo (works with no keys)

1. On http://localhost:3000/session type `RAG retrieves relevant documents using embeddings. The model then answers from those documents.`
   Each new note gets a diagram in the right-hand pane (click a note to switch).
2. Type another note that shares wording with an earlier one. A dashed amber
   **related (unconfirmed)** link appears under both notes.
3. Open **Memory map**. Notes are nodes, the unconfirmed link is a dashed amber edge. Click a
   node for its note, diagram and links, then **Confirm** (edge turns solid) or **Remove**.
   Grey nodes have no review history yet; strength colours and the red fragile marker arrive with Phase 3.

## Phase 3 demo (works with no keys)

1. On /session capture two or three ideas ("Reranking reorders retrieved chunks by relevance before
   generation. Chunk overlap keeps context across boundaries."). Each note gets a cloze and a question.
2. **Quiz me** (or say it) asks what is due. Answer wrongly or press **I forgot** to climb the ladder:
   nudge, partial, then the answer with an explanation and a diagram. The grade follows how much help
   you needed. Doing a full reveal twice in a row marks the note fragile and brings it back within a day.
3. Type `explain reranking`: you get a short spoken explanation, a diagram and **Save as note**.
   Then type `I don't get it`: the note is marked fragile and explained again in simpler words.
4. Type `read me my notes on reranking`; use next, repeat, slower, faster, stop.
5. On **Memory map**, notes you have reviewed take a red to green strength colour, fragile ones get a red
   border, and **Quiz me on this** practises that one note.

## Phase 4 demo

1. Open **Sources**, paste a link (or text), press **Add source**. It moves through fetching, chunking and
   extracting, then shows `Filed N notes under AI Engineering, linked M.` Each note is dashed
   (*From source, unconfirmed*) with its citation: the verbatim quote and chunk.
2. **Undo** any item, then **Approve all**. Approved notes count and are quizzed.
3. Add the same link again (even with `?utm_source=...`): it is recognised, not added twice.
4. By voice: say `what did you file?`, then `yes` to approve or `no` to remove it all.

### n8n (ingest from anywhere)

```bash
make dev                # starts n8n at http://localhost:5678 too
make n8n-import         # loads the three workflows and activates them
```

| Workflow | What it does |
|---|---|
| `ingest-url` | `POST /webhook/ingest-url` with `{"url": "...", "track": "ai-eng"}` and header `X-Recall-Secret` |
| `ingest-inbox` | watches `n8n/inbox/`: drop a PDF, or a `.txt`/`.md` file with links |
| `sync-export` | nightly, writes every note as Markdown into `n8n/exports/` |

```bash
curl -X POST http://localhost:5678/webhook/ingest-url \
  -H "Content-Type: application/json" -H "X-Recall-Secret: $RECALL_SHARED_SECRET" \
  -d '{"url": "https://example.com/some-article"}'
```
