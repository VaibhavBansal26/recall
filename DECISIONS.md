# Decisions and deviations from the spec

Newest first. Anything that differs from `CLAUDE.md` goes here with the reason.

## Phase 2.5: hosted backend and installable PWA

The user asked for one app on laptop, iPhone and iPad, synced. This overrides spec rule 7 (bind to
localhost, no auth) and the "local-first" framing, by decision of the user.

- **One always-on backend on a cloud VM; every device is a client.** Sync is therefore trivial
  (one source of truth) and there are no merge conflicts. Chosen over a native iOS app with an
  offline store and sync, which is a much larger build. Trade-off: no offline use. The service
  worker only shows an offline page.
- **Auth: one passphrase exchanged for a signed session cookie (itsdangerous), 30 days.** HttpOnly,
  SameSite=Lax, Secure in production. Login is rate limited (5 failures per 10 minutes per address).
  `user_id` columns are kept, so multi-user stays possible. Auth is off when `AUTH_PASSPHRASE` is
  empty, which keeps local development friction-free. In `ENVIRONMENT=production` the backend refuses
  to start without a 12+ character passphrase, `SESSION_SECRET` and `COOKIE_SECURE=true`.
- **The WebSocket authenticates its own handshake** (cookie plus `Origin` check), since cookies
  travel on cross-site WebSocket requests.
- **Single public origin behind Caddy.** `/api`, `/ws`, `/healthz` go to the backend, the rest to
  Next.js. That removes CORS in production, lets the cookie and WebSocket work as same-origin, and
  gives automatic HTTPS (required for the microphone on iOS). The frontend is built with an empty
  `NEXT_PUBLIC_API_URL` meaning "same origin"; the dev stack still talks to `:8000` with CORS and
  credentials.
- **"Sync" between open devices is refresh-on-focus plus a 30 second poll**, not a live push. A note
  captured on one device shows on another when it is next focused. Live push is in `IDEAS.md`.
- **Postgres, backend and frontend are not published in production**; only Caddy's 80/443 are.
  `scripts/backup.sh` and `restore.sh` use `pg_dump`.
- **Not verified:** the service worker registering and Add to Home Screen on real iOS Safari, iOS
  microphone behaviour, and a real domain with Let's Encrypt. The production stack was tested
  locally over plain http on localhost with fakes.

## Phase 2

- **Mermaid is validated by a strict Python parser (`services/mermaid.py`), not Mermaid's own.**
  Mermaid's parser only exists in JavaScript. The Python parser covers flowchart, sequenceDiagram
  and mindmap, is deliberately narrower than Mermaid, and returns line-numbered errors that are fed
  back for the one retry. The frontend also calls `mermaid.parse` before rendering and shows the
  source if that fails. Flow is: generate, validate, retry once with the error, then a plain
  step list built from the LLM's steps (or the note's own sentences).
- **Spec columns added:** `note_links.confirmed` (assistant links stay unconfirmed and render
  dashed until accepted; section 2 rule 6), and a unique `diagrams.note_id` (one current diagram
  per note, regeneration replaces it).
- **Capture is now two graph nodes, `capture` then `enrich`.** Notes are sent to the UI as soon as
  they exist; the diagram and link proposals follow when ready.
- **Link proposals:** nearest same-track notes above 0.35 cosine similarity are shown to the deep
  model, which may answer "no link". Direction: "from" side must be understood first
  (`prerequisite`), is the example (`example_of`), or is the component (`appears_in`).
- **`GET /api/graph` already returns `strength` and `fragile`** but both are null/false until
  Phase 3 produces FSRS state. The map colours and markers are wired and tested.
- **"Quiz me on this" is present but disabled** until the recall engine exists.
- **Docker gotcha:** regenerate `frontend/package-lock.json` with the container's npm
  (`docker run --rm -v "$PWD/frontend":/app -w /app node:20-slim npm install --package-lock-only`)
  after adding dependencies, or `npm ci` in the image fails on optional wasm packages.
- **Multi-device use is now a requirement (laptop + iPhone + iPad, synced).** See Phase 2.5.

## Phase 1

- **Every external service has a fake, selected by env** (`VOICE_PROVIDER`, `LLM_PROVIDER`,
  `EMBEDDING_PROVIDER`; all default to `fake`). No keys existed, so the real Deepgram,
  ElevenLabs, Anthropic and Voyage clients are written but have **not been exercised against the
  live services**. Their parsing/assembly logic that does not need the network is unit tested.
- **Embeddings use Voyage (`voyage-3`, 1024 dims).** Anthropic has no embeddings API. The
  `notes.embedding` column is `vector(1024)`; changing model dimension needs a migration.
- **The spoken reply bypasses the LangGraph graph.** The graph runs the `capture` node in the
  background (extract, dedup, merge), while the short spoken acknowledgement streams straight from
  the fast model so first audio is not blocked by note extraction (section 2, rule 1). The router
  node arrives with the second mode.
- **Capture undo needs history, so `capture_events` is a new table** (not in section 5). It stores
  the pre-merge title/body/embedding. `utterances.interrupted` is also new, for keeping the partial
  assistant turn after barge-in (section 13).
- **Dedup = same title (case-insensitive) or cosine similarity above 0.88**, scoped to the track.
  A match merges via an LLM merge prompt rather than creating a second note.
- **Not built yet from section 13:** backchannel acknowledgements ("mm, let me pull that up"), a
  server-side `vad.py` (only the client VAD hint exists). Review items per note (section 6.1) wait
  for the `review_items` table in Phase 3.
- **Barge-in has three triggers:** client VAD hint (`speech_start`), a partial transcript with 2 or
  more words, or a new final turn. Open-mic needs the browser's echo cancellation so the assistant
  does not interrupt itself; headphones are safer.
- **`httpx` is now a runtime dependency** (Voyage and ElevenLabs clients), so it moved out of the
  dev group.

## Phase 0

- **`VOICE_PROVIDER` defaults to `fake`, not `pipeline`.** The spec says `pipeline` is
  the default, but it needs Deepgram/ElevenLabs keys that do not exist yet. Per section 16
  we stub with the Fake provider. Flip the env var once the keys are in (Phase 1).
- **Phase 0 migration only creates `tracks`, `sessions`, `utterances`** (plus
  `CREATE EXTENSION vector`). Remaining tables from section 5 arrive in the migration of
  the phase that first needs them, so each phase's schema is exercised by its own code.
- **Tracks are synced from `backend/app/tracks/*.yaml` into the `tracks` table on
  startup** (upsert by slug). Only `ai_eng.yaml` exists until Phase 6.
- **psycopg 3 for both sync (Alembic) and async (app) SQLAlchemy engines.** One driver,
  one URL, no asyncpg/psycopg2 split.
- **`uv` for Python dependency management** (lockfile + reproducible Docker build).
- **Frontend runs `next dev` in Docker** (hot reload, local-first, single user). No
  production image in v1.
- **Interrupting a fake reply discards the partial assistant turn.** The "keep partial
  turn marked as interrupted" behaviour (section 13) lands with real barge-in in Phase 1.
- **REST types are generated** from the OpenAPI schema (`make gen-api`). WebSocket events
  are not in OpenAPI, so their TypeScript types are hand-written in
  `frontend/lib/events.ts` and mirror `backend/app/voice/events.py`.
