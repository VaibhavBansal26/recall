# Recall: project rules

This file is the source of truth for the build. The full product spec the project was
started from is kept below, with section 1 to 16 numbering kept. Work **one phase at a time**
and do not start the next phase until the current phase's acceptance checks pass and the
user says go. Log any deviation in `DECISIONS.md`; park out-of-spec ideas in `IDEAS.md`.

## Current state

Phases 0, 1, 2 and 2.5 (hosted backend with passphrase login, Caddy HTTPS, installable PWA; see `DEPLOY.md`) are built, verified with fakes only. Spec rule 7 (localhost, no auth) is superseded by the user for production. Phase 3 (recall engine) is built too. Phase 4 (ingestion and n8n) is built. Next: Phase 5 (daily brief and stats).

## Commands

See `README.md` / `Makefile`: `make dev`, `make test`, `make lint`, `make migrate`, `make gen-api`.

## Conventions already in place

- Backend: Python 3.12 via `uv`, FastAPI, SQLAlchemy 2 async (psycopg 3), Alembic, Pydantic v2.
  `ruff` + `mypy --strict` must pass.
- Tracks are YAML in `backend/app/tracks/` synced to the `tracks` table at startup.
- WebSocket contract: `backend/app/voice/events.py`, mirrored by hand in `frontend/lib/events.ts`.
- REST types are generated: `make gen-api` after changing any API schema.
- `VOICE_PROVIDER`, `LLM_PROVIDER`, `EMBEDDING_PROVIDER` default to `fake` until API keys exist.
- Prompts are versioned files in `backend/app/agent/prompts/`; LLM calls go through `app/llm`.

---

# Product spec (verbatim from the project brief)

You are building a voice-first learning companion for one user (single-tenant, local-first, I run it myself). I talk to it. It turns the conversation into structured notes, diagrams, and a linked memory map. When I forget something, it helps me recall with a hint ladder, reads my notes back with explanation, and quizzes me on what is due. I can feed it external material (links, PDFs, YouTube) and it files that into the right track.

## 1. Tracks

Every note, session, and review item belongs to exactly one track.

| Track slug | Purpose | Special behaviour |
|---|---|---|
| `ai-eng` | Learning AI engineering (LLMs, agents, RAG, evals, systems) | Concept notes, architecture diagrams |
| `dsa` | Data structures and algorithms | Pattern notes, step-by-step visual walkthroughs, complexity |
| `solutions` | Discussing solution approaches to a specific question | Capture problem, approaches tried, tradeoffs, final choice |
| `english` | Improving spoken English articulation | Teach-back mode, filler-word and structure scoring |

**Phase 1 ships `ai-eng` only.** The track system must be data-driven (a `tracks` table plus a per-track prompt/config file in `backend/app/tracks/`) so adding a track is config plus prompts, not new code paths.

## 2. Non-negotiable product rules

1. **Voice must not feel robotic.** Target under 800 ms from end of my speech to first audio. Stream everything. Support barge-in (I interrupt, it stops within 200 ms). Spoken replies are short sentences, conversational connectors, no bullet-style speech, no markdown read aloud.
2. **Visual explanations always include a diagram**, not words alone. When explaining a concept or walkthrough, generate a Mermaid diagram or simple step diagram alongside the spoken answer.
3. **Spoken answers follow structure**: what, how, why, impact, with one sentence leading into the next. Applies to the agent's explanations and to the `english` track scoring.
4. **Simplify on request.** If I say "I don't get it", "dumb it down", or re-ask, switch to simple words, one step at a time, one concrete example per step, and mark the node as fragile.
5. **Forgetting drives the system.** Questions are chosen by what is due (spaced repetition), not randomly.
6. **Never invent facts into notes.** Notes only contain what I said, what the source material said, or what I accepted from the assistant. Anything the assistant adds is stored with `origin = 'assistant'` and shown differently until I confirm it.
7. **Single user, no auth in v1.** Bind to localhost. Keep a `user_id` column anyway so multi-user is not a rewrite.

## 3. Stack (use exactly this unless blocked; tell me if you deviate)

- **Backend**: Python 3.12, FastAPI, LangGraph for the agent loop, Pydantic v2 for all contracts, SQLAlchemy 2 + Alembic.
- **DB**: Postgres 16 with `pgvector`, run via `docker-compose.yml`.
- **Frontend**: Next.js 14 (App Router), TypeScript, Tailwind, React Flow for the memory map, `mermaid` for diagrams, Zustand for client state.
- **Voice**: a `VoiceProvider` interface with two implementations behind env config.
  - `pipeline` (default): browser mic → WebSocket → streaming STT (Deepgram) → LLM stream → streaming TTS (ElevenLabs Flash or Cartesia) → audio chunks back over the same WebSocket.
  - `realtime` (optional, Phase 6): a speech-to-speech provider (OpenAI Realtime or ElevenLabs Conversational).
  - Voice choice, speed, and warmth are config. Use one consistent warm, calm voice. No voice switching mid-session.
- **LLM**: Anthropic Claude via the official SDK. Model names come from env vars `LLM_FAST_MODEL` (live voice turns) and `LLM_DEEP_MODEL` (note structuring, diagram generation, ingestion). Do not hardcode model strings.
- **Embeddings**: configurable via env, default to an API embedding model. Store in pgvector.
- **Spaced repetition**: the `fsrs` Python package (FSRS algorithm). Do not hand-roll SM-2.
- **Automation**: n8n (self-hosted in docker-compose) for ingestion triggers, cron, and sync only. See section 8.
- **Tests**: pytest + httpx for backend, Vitest for frontend, Playwright for one end-to-end smoke test.

Hard rule: **the live voice turn loop never goes through n8n.** n8n adds latency. n8n calls the backend; the backend never waits on n8n inside a voice turn.

## 4. Architecture

```
 Browser (Next.js)
 ┌────────────────────────────────────────────────────────┐
 │ Mic ─► WS audio ─────────────┐        ┌─► Speaker      │
 │ Notes pane │ Diagram pane │ Memory map │ Review UI      │
 └──────────────────────────────┼────────┼────────────────┘
                                ▼        ▲
 FastAPI                    VoiceProvider (STT ► LLM ► TTS, streaming, barge-in)
 ┌────────────────────────────────────────────────────────┐
 │ LangGraph agent                                        │
 │  router ─► capture │ explain │ recall │ teachback │ ... │
 │      │                                                 │
 │      ▼ tools                                           │
 │  note_store │ graph_store │ diagram_gen │ review_sched │
 │  ingest     │ retrieval (hybrid: vector + keyword)     │
 └───────────────┬─────────────────────────────┬──────────┘
                 ▼                             ▲
         Postgres + pgvector            n8n (ingest, cron, sync)
```

### Agent graph (LangGraph)

State (Pydantic): `session_id`, `track`, `mode`, `transcript_window`, `active_note_ids`, `pending_questions`, `confusion_flags`.

Nodes:
- `router`: classifies each user turn into a mode: `capture`, `explain`, `read_back`, `recall_quiz`, `teach_back`, `ingest_review`, `chitchat`. Cheap model, structured output.
- `capture`: extracts atomic notes from what I said. Does **not** interrupt me mid-thought; confirms briefly ("Got it, noted") and keeps listening.
- `explain`: explains a concept in structured what/how/why/impact form, attaches a diagram.
- `read_back`: reads selected notes aloud with explanation, then asks one question.
- `recall_quiz`: pulls due items, asks one at a time, runs the hint ladder, grades, updates FSRS.
- `teach_back`: I explain a concept; it scores clarity (section 7).
- `ingest_review`: when new material lands, summarises what was filed and where, asks me to confirm.

Every node returns both **spoken text** (short, natural) and **display payload** (notes, Mermaid, links). They are generated separately so spoken output never contains markdown.

## 5. Data model

Postgres tables (write Alembic migrations):

- `tracks(id, slug, name, config jsonb)`
- `sessions(id, user_id, track_id, mode, started_at, ended_at, summary)`
- `utterances(id, session_id, speaker, text, started_at, confidence)`
- `notes(id, user_id, track_id, title, body_md, origin ENUM('user','source','assistant'), confirmed bool, source_id nullable, created_at, updated_at, embedding vector)`
- `note_links(id, from_note_id, to_note_id, kind ENUM('prerequisite','related','example_of','contrasts','appears_in'), origin)`
- `diagrams(id, note_id, kind ENUM('mermaid','steps'), source text, created_at)`
- `sources(id, user_id, track_id, kind ENUM('url','pdf','youtube','text'), uri, title, status, raw_text, created_at)`
- `source_chunks(id, source_id, idx, text, embedding vector)`
- `review_items(id, note_id, prompt_kind ENUM('cloze','question','explain','teachback'), prompt, answer, fsrs_state jsonb, due_at, last_reviewed_at, fragile bool)`
- `review_logs(id, review_item_id, reviewed_at, grade, hint_tier_used smallint, latency_ms, session_id)`
- `confusion_events(id, session_id, note_id nullable, trigger text, created_at)`
- `articulation_scores(id, session_id, note_id nullable, clarity, structure, filler_rate, wpm, feedback jsonb, created_at)`

Indexes: HNSW on `notes.embedding` and `source_chunks.embedding`; GIN full-text on `notes.title || body_md`; btree on `review_items.due_at`.

## 6. Core behaviours in detail

### 6.1 Capture
- Notes are atomic (one idea each), titled as a claim or question, body in Markdown, 1-5 sentences.
- On each capture turn: extract candidate notes → run retrieval for near-duplicates (cosine > 0.88 or title match) → **merge or link instead of duplicating**. Show the merge decision in the UI with an undo.
- Auto-propose links to existing notes. Links created by the assistant have `origin='assistant'` until I confirm.
- Create 1-3 review items per note (cloze and/or question). Cap per session so I am not flooded.

### 6.2 Diagrams and memory map
- After a concept is captured or explained, generate a Mermaid diagram (flowchart, sequence, or mindmap as fits). Validate it by parsing before saving; if invalid, retry once with the parser error, then fall back to a simple step list.
- The **memory map** is a React Flow graph of notes and links, filterable by track, coloured by memory strength (from FSRS retrievability), with fragile nodes visibly marked. Clicking a node opens the note, its diagram, and a "quiz me on this" button.
- DSA track (later): walkthroughs render as step-by-step position diagrams (e.g. pointer positions on an array per step), not prose.

### 6.3 Hint ladder (recall_quiz)
For each due item:
1. Ask the question aloud. Wait for my answer.
2. If I am wrong or say "I forgot": **Tier 1 nudge** (point at the related note or pattern, no answer).
3. Still stuck: **Tier 2 partial** (reveal the first piece or structure).
4. Still stuck: **Tier 3 reveal + explain**, with a diagram, then ask a quick follow-up to confirm understanding.
- Log `hint_tier_used`. Map to FSRS grade: correct unaided = Good/Easy, Tier 1 = Hard, Tier 2 or 3 = Again. Needing Tier 3 twice in a row sets `fragile = true` and shortens the next interval.
- Grading of free-form spoken answers is done by the LLM against the stored answer with a rubric, returning structured output `{correct: bool, partial: bool, missing_points: []}`. Be lenient on wording, strict on meaning.

### 6.4 Read-back
"Read me my notes on X" → retrieve notes for X, order by prerequisite links, read each with a one-line explanation of why it matters, show the diagram, and end with one question. Pace is controllable by voice ("slower", "next", "repeat", "skip").

### 6.5 Confusion detection
Triggers: phrases like "wait", "I don't get it", "what do you mean", the same question asked twice within a session, or a long silence after an explanation. On trigger: log a `confusion_event`, set the related note `fragile`, and re-explain in simplified form (rule 4). No manual flagging required from me.

### 6.6 Daily brief
A 3-5 minute spoken session: yesterday's three weakest nodes, one question each, then a one-line "what's due today" summary. Triggered by an n8n cron calling `POST /api/sessions/daily-brief`; the frontend shows a "Your brief is ready" prompt and starts it on click (browsers block autoplay audio).

## 7. English articulation track (build last)

Teach-back mode: I explain a concept out loud. The pipeline:
1. Keep the raw transcript with word timestamps.
2. Compute objective metrics in code, not by LLM: words per minute, filler-word rate (um, uh, like, you know, basically, actually), long pauses, sentence length distribution.
3. LLM scores structure against what / how / why / impact (present or missing each), plus clarity, and gives 2-3 concrete suggestions with a rewritten version of one weak sentence.
4. Store in `articulation_scores`, chart trends over time.
5. Feedback is spoken gently and briefly: one thing done well, one thing to fix.

## 8. n8n workflows (export JSON into `n8n/workflows/`)

n8n only does these, and each calls the backend over HTTP with a shared secret header:

1. **ingest-url**: webhook receives a URL (from browser extension, share sheet, or email) → `POST /api/sources` with `{kind, uri, track_hint}`.
2. **ingest-inbox**: watches a folder or an email label for PDFs and links → same endpoint.
3. **daily-brief-cron**: every morning at my local time → `POST /api/sessions/daily-brief`.
4. **review-nudge**: if more than N items are overdue by evening → send me a notification (email or push).
5. **sync-export** (optional): nightly export of notes to Markdown files and/or Notion.

The backend, not n8n, does all parsing, chunking, classification, and note creation, so ingestion logic stays testable in Python.

## 9. Ingestion pipeline (backend)

`POST /api/sources` → async job:
1. Fetch and extract text (web articles, PDF, YouTube transcript).
2. Chunk (semantic-ish, ~500-800 tokens, with overlap), embed, store `source_chunks`.
3. Classify to a track and topic (use `track_hint` if given; otherwise LLM classification with confidence; if confidence is low, ask me by voice or UI).
4. Extract candidate notes **with citations back to chunks**, run the same dedup/merge as capture, and create them with `origin='source'`.
5. Create review items.
6. Emit a summary I can approve: "Filed 7 notes under AI Eng, merged 2 into existing notes, linked 4." with undo per item.

## 10. API surface (FastAPI)

- `WS /ws/voice`: bidirectional audio + control events (`interrupt`, `mode`, `track`).
- `POST /api/sessions`, `GET /api/sessions/{id}`
- `POST /api/sessions/daily-brief`
- `GET/POST/PATCH /api/notes`, `GET /api/notes/{id}/links`
- `GET /api/graph?track=` (nodes + edges + strength for React Flow)
- `GET /api/reviews/due`, `POST /api/reviews/{id}/grade`
- `POST /api/sources`, `GET /api/sources/{id}`
- `GET /api/stats` (retention, streaks, weak nodes, articulation trend)
- `GET /healthz`

All request and response bodies are Pydantic models. Generate an OpenAPI client for the frontend.

## 11. Repo layout

```
recall/
├─ CLAUDE.md
├─ docker-compose.yml          # postgres+pgvector, n8n, backend, frontend
├─ .env.example
├─ backend/
│  ├─ app/
│  │  ├─ main.py
│  │  ├─ config.py
│  │  ├─ db/ (models, migrations)
│  │  ├─ voice/ (provider.py, pipeline.py, realtime.py, vad.py, barge_in.py)
│  │  ├─ agent/ (graph.py, state.py, nodes/, prompts/)
│  │  ├─ tracks/ (ai_eng.yaml, dsa.yaml, solutions.yaml, english.yaml)
│  │  ├─ services/ (notes.py, graph.py, diagrams.py, reviews.py, ingest.py, scoring.py)
│  │  └─ api/ (routers)
│  └─ tests/
├─ frontend/
│  ├─ app/ (session, notes, map, review, sources, stats)
│  ├─ components/ (VoiceOrb, TranscriptStream, NotePane, MermaidView, MemoryMap, HintLadder)
│  └─ lib/ (ws client, audio worklet, api client)
└─ n8n/workflows/
```

## 12. Frontend requirements

- **Session screen**: a calm voice orb (idle / listening / thinking / speaking states), live transcript, a notes pane that fills in as I talk, and a diagram pane. Push-to-talk and open-mic toggle. Visible interrupt button.
- **Memory map screen**: React Flow, track filter, strength colouring, fragile markers, click-to-open.
- **Review screen**: shows the current question, hint-tier controls (also voice-driven), and a grade summary.
- **Sources screen**: ingestion status, what was filed, approve/undo.
- **Stats screen**: due today, retention curve, weakest nodes, articulation trend.
- Audio capture via AudioWorklet, 16 kHz mono PCM, with client-side VAD hint. Playback via a jitter-buffered queue that can flush instantly on barge-in.
- Keyboard-accessible, readable in light and dark mode.

## 13. Voice pipeline requirements

- Streaming STT with partial and final transcripts; endpointing tuned so it does not cut me off mid-thought (configurable silence threshold, default ~700 ms, longer in `capture` mode).
- LLM streams tokens; **sentence-chunk the stream and send each sentence to TTS as soon as it is complete**.
- Spoken text is post-processed: strip markdown, expand symbols, no URLs read aloud, numbers spoken naturally.
- Barge-in: VAD on the mic during playback; on speech onset, stop TTS, flush the client audio buffer, cancel the in-flight LLM and TTS streams, and keep the partial assistant turn in the transcript marked as interrupted.
- Short backchannel acknowledgements while the model is working on a long step ("mm, let me pull that up"). Rate-limited so it is not annoying.
- Log per-turn latency (STT final → first LLM token → first audio byte) and show it in a debug overlay. These numbers are how we judge "not robotic".
- Provide a `FakeVoiceProvider` (text in, text out, canned audio) so every non-voice feature is testable without API keys.

## 14. Phases and acceptance checks

Work in this order. After each phase: run tests, run the app, and give me a short demo script I can follow.

**Phase 0: Skeleton**
- docker-compose up brings up Postgres, backend, frontend, n8n.
- Migrations run. `/healthz` works. `FakeVoiceProvider` works end to end with typed text.
- Accept: I can open the app, type a message in the `ai-eng` track, and see an utterance stored.

**Phase 1: Capture to notes**
- Real streaming voice (pipeline provider), live transcript, capture node, atomic notes, dedup/merge with undo, embeddings.
- Accept: I talk for two minutes about RAG; I get 4-8 clean atomic notes, no duplicates on a second pass over the same topic, and I never feel cut off mid-sentence.

**Phase 2: Diagrams and memory map**
- Mermaid generation with validation and fallback, link proposals, React Flow map.
- Accept: each captured concept has a rendering diagram; the map shows linked notes; unconfirmed assistant links look different.

**Phase 3: Recall engine**
- FSRS scheduling, review items, `recall_quiz` with the hint ladder, grading, fragile flags, confusion detection, read-back mode.
- Accept: after a day, `GET /api/reviews/due` returns sensible items; a voice quiz runs end to end; Tier 3 twice sets fragile and shortens the interval; "I don't get it" triggers a simplified re-explanation with a diagram.

**Phase 4: Ingestion and n8n**
- `/api/sources`, chunking, classification, cited note extraction, merge, approval UI. Three n8n workflows exported and working.
- Accept: sending a URL through the n8n webhook produces filed, cited notes in the right track within a minute, with a summary I can approve.

**Phase 5: Daily brief and stats**
- Daily brief session, review-nudge workflow, stats page.
- Accept: cron-triggered brief shows a ready prompt and runs a 3-minute session.

**Phase 6: More tracks and polish**
- Add `dsa`, `solutions`, `english` tracks via config and prompts. Build articulation scoring (section 7). Optional `realtime` voice provider.
- Accept: each track produces appropriately different notes and behaviour; teach-back produces objective metrics plus spoken feedback.

## 15. Engineering standards

- Pydantic models for every boundary (API, tool inputs, LLM structured outputs). Validate LLM JSON and retry once on failure.
- Prompts live in files under `agent/prompts/`, versioned, never inline strings scattered in code.
- Every LLM call logs model, tokens, latency. Keep a simple cost counter per session.
- Idempotent ingestion (same URL twice does not duplicate).
- Secrets only via env. Provide `.env.example`. Never commit keys.
- Type hints everywhere, `ruff` + `mypy` on backend, `eslint` + `tsc` on frontend, CI-ready scripts in a `Makefile` (`make dev`, `make test`, `make lint`, `make migrate`).
- Write tests for: dedup/merge, FSRS grade mapping, hint-ladder state machine, Mermaid validation fallback, confusion triggers, sentence-chunking for TTS, barge-in cancellation logic (with fakes).
- Keep a `DECISIONS.md` for any deviation from this spec and why.

## 16. How to work with me

- Before each phase, output a short plan (files to create, order, risks) and wait for my "go" only if something is ambiguous; otherwise proceed.
- If a required API key or choice is missing, stub with the Fake provider, note it, and continue.
- Prefer small, working vertical slices over broad scaffolding.
- At the end of each phase: list what works, what is stubbed, what to try, and the exact commands to run.
- Do not add features not in this spec. Put ideas in `IDEAS.md` instead.
