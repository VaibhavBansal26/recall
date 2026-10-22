# Decisions and deviations from the spec

Newest first. Anything that differs from `CLAUDE.md` goes here with the reason.

## Speech-to-text provider (post Phase 6)

- **ElevenLabs Scribe v2 realtime is now the default STT** (`STT_PROVIDER=elevenlabs`), so one ElevenLabs
  key covers listening and speaking. Deepgram stays as `STT_PROVIDER=deepgram`. The ElevenLabs client
  follows their published websocket protocol but has **not been run against the live service**: only
  its message handling is unit-tested. Check the first real session (Debug panel) before relying on it.
- Segments commit on the server's voice-activity detection using the track's silence setting;
  push-to-talk release sends a short silence with `commit` set to flush.

## Phase 6: more tracks and articulation scoring

- **The `realtime` voice provider is not built.** The spec calls it optional. It needs an
  OpenAI Realtime or ElevenLabs Conversational key and a second turn loop that bypasses the
  router, notes and hint ladder, so it would be a parallel product rather than a provider swap.
  Parked in `IDEAS.md`. `VOICE_PROVIDER` still accepts `fake` and `pipeline`.
- **Tracks differ through YAML `guidance` blocks, not code paths.** Each track can add text for
  capture, explain, quiz, review, links, diagram and teach_back. It is appended to the shared prompt
  (`guidance_for`). ai-eng has none, so its prompts are byte-for-byte what they were. Only two things
  are flags: `walkthrough_diagrams` (dsa) and the longer `capture_silence_ms` (english).
- **DSA walkthroughs are a new diagram kind, `walkthrough`**, stored as validated JSON (array, pointers
  per step, highlighted cells, caption). The model drafts it, code validates indexes and sizes, one
  retry with the reason, then it falls back to a Mermaid diagram. It is not a Postgres-enum rename:
  the value was added with `ALTER TYPE ... ADD VALUE`.
- **Objective metrics are computed in code, never by the LLM** (`services/scoring.py`). Pace needs
  word timings, so typed input shows "–" for pace instead of a made-up number. Word timings from
  Deepgram are stored in `utterances.words`.
- **Filler "like" is a heuristic.** It counts "like" only when it is not a verb or comparison
  (for example "I like it", "like a tree" are not fillers). It will be wrong sometimes; um, uh, er,
  hmm, basically and actually are exact. "you know" counts only when set off by punctuation.
- **LLM scoring is checked against the transcript.** A beat (what/how/why/impact) counts as present
  only if its evidence quote appears verbatim in what was said; otherwise it is downgraded to missing.
  The rewrite of a weak sentence is dropped unless that sentence is really in the transcript.
  Structure is computed from the beats (present/4 x 100); the LLM supplies clarity.
- **Teach-back segments are not captured as notes.** While listening, the assistant stays silent
  and stores utterances only; "I'm done" (or the button) ends and scores it. Under 15 words is
  "too short" and is not stored as a score.
- **The articulation trend spans all tracks**, one point per day, because the skill is the same
  whichever topic you explained. It is shown as four small charts (one scale each), not one
  dual-axis chart.
- **The track choice is per device** (localStorage), not synced, so the phone can be on English
  while the laptop is on DSA.
- **The fake LLM does not show real differences between tracks.** Tests prove each track's guidance
  reaches the right prompts; whether a real model writes visibly different notes is unmeasured
  until keys exist.

## Phase 5: daily brief and stats

- **"Today" is the user's day.** `USER_TIMEZONE` (an IANA name, validated at startup) decides which
  date a brief belongs to, what "due today" means (until local midnight, DST-aware) and the day buckets
  in the stats. n8n's schedules use the same zone.
- **The brief picks the three weakest notes, one question each.** Weakness = forgetting (1 minus FSRS
  retrievability) + 0.5 if fragile + 0.25 per Again/Hard in the last 36 hours (capped at 4). "Yesterday's
  weakest" is therefore current weakness with a recent-misses boost, not a literal one-day window. Each
  note contributes its weakest question. Fewer than three weak notes are topped up from what is due, and
  unconfirmed or never-reviewed notes are never "weak". Nothing to ask gives an `empty` brief and no prompt.
- **One brief per day, cron-safe.** `POST /api/sessions/daily-brief` returns today's brief if it exists
  (200, `created: false`); `?force=true` rebuilds a brief that has not been started. Table `daily_briefs`
  (new, unique per user and date).
- **It starts on a click.** The banner "Your brief is ready" (shown wherever you are, hidden on the review
  page) opens `/review?brief=ID`, which starts the spoken session over the WebSocket. Saying "start my
  brief" also works and builds it first if the cron has not run.
- **Spoken shape:** a greeting, one question per weak note through the normal hint ladder and FSRS
  grading, then the summary plus "and that's your brief, N reviews are due today". Ending early counts
  as done so the banner does not nag.
- **Stats** (`GET /api/stats`): due now and today, streaks (a streak survives until the end of today),
  7 and 30 day retention (Hard, Good or Easy over all reviews, FSRS's "true retention"), the share
  answered without a hint, mean retrievability now, a 30 day retention curve (days with no reviews are
  gaps, not zeros), weakest notes, sources waiting for approval.
- **Articulation trend is an empty list** until the English track exists (Phase 6).
- **Machine access:** n8n may call `POST /api/sessions/daily-brief` and `GET /api/stats` with the shared
  secret. `GET /api/briefs/ready` stays browser-only.
- **Two more n8n workflows:** `daily-brief-cron` (07:30 in `USER_TIMEZONE`) and `review-nudge` (18:00: if
  `due_now` is at least `NUDGE_THRESHOLD`, default 10, and `NUDGE_URL` is set, POST a plain-text reminder
  containing only the count; an ntfy topic works). Email needs credentials n8n cannot ship in a workflow
  file, so push via ntfy is the built-in route and an email node can be added in the n8n editor.
- **Retention chart:** one series, so no legend; 2 px line, soft area wash, labelled end value, hover
  tooltip, and a table view for accessibility.
- **Not verified:** a real morning on a real VM (the cron fires on schedule), push delivery to an actual
  phone (tested against a local listener), and the brief's spoken pacing with real TTS and the 3 to 5
  minute target (it is three questions through the hint ladder).

## Phase 4: ingestion and n8n

- **Pipeline:** fetch/extract, chunk (about 450 words, 60 overlap, roughly 600 tokens), embed into
  `source_chunks`, classify, extract notes with citations, file with the same dedup/merge as live
  capture (`services/capture.file_candidate`), then diagrams, link proposals and review items. A
  source is `ready` as soon as its notes are filed; enrichment continues in the background.
- **Citations are verified, never trusted.** The model must give a verbatim quote and chunk number
  per note. A note is kept only if the quote really occurs in that chunk (case, punctuation and spacing
  ignored, at least 3 words). Notes with no verifiable quote are dropped. Stored in `note_citations`.
- **Approval = confirmation.** Source notes are created `origin='source'`, `confirmed=false`, shown
  dashed, and become confirmed on **Approve**. **Quizzes only ask about confirmed notes**, so unapproved
  source notes and unsaved assistant notes are never quizzed. This replaces "create review items after
  approval": items are made at ingest (as the spec orders it) but stay out of the queue until approval.
- **Undo per item** reuses `capture_events` (now with `source_id`). Undoing a created note deletes it
  and its event, so the item disappears from the source's list.
- **Idempotent.** Links are normalised (scheme/host case, default ports, fragments, tracking params,
  YouTube URL forms); pasted text and PDFs by content hash. `sources` is unique on `(user_id, uri)`. A
  failed source submitted again is retried, not duplicated.
- **Classification.** With a `track_hint` or a single track there is no LLM call. Otherwise the fast
  model picks a track with a confidence; below 0.6 (or an unknown slug) the source waits in
  `needs_track` and the UI asks. Answering resumes from where it stopped (no refetch, no re-embed).
- **The server fetches URLs it is given, so there is an SSRF guard:** http(s) on ports 80/443 only, every
  hop's host must resolve to public addresses only (private, loopback, link-local, cloud metadata, CGNAT
  and IPv4-mapped ranges refused), redirects followed by hand and re-checked, the connection pinned to the
  checked address, 8 MB and 15 s caps.
- **Machine auth.** n8n calls `/api/sources*` and `/api/export` with `X-Recall-Secret` (constant-time
  compare to `RECALL_SHARED_SECRET`). The secret opens nothing else. It must be 16+ characters and not
  the placeholder; empty disables it.
- **Three n8n workflows** (`n8n/workflows/`, generated by `n8n/build_workflows.py`, targets n8n 2.44.5):
  `ingest-url` (webhook, checks the secret itself, so it is safe to expose through Caddy),
  `ingest-inbox` (watches `/files/inbox`: PDFs are uploaded, links found in text/Markdown files are
  ingested), and `sync-export` (nightly Markdown export of all notes). The spec lists review-nudge and
  daily-brief-cron under Phase 5, so the third Phase 4 workflow is the optional sync-export.
- **n8n 2.x specifics.** Pinned image. The Local File Trigger node is off by default, so it is enabled
  while Execute Command stays excluded. File access is limited to `/files`. In regular mode workflows
  load via `make n8n-import` (import, publish, restart).
- **Not built:** the email-label inbox (only a folder), and a browser extension or share sheet (the
  webhook is the integration point).
- **`ingest_review` voice mode:** "what did you file?" summarises the newest ready source; yes confirms,
  no removes everything it added, "not now" leaves it waiting.
- **Not verified:** extraction quality and citation yield with a real model (the fake LLM files the first
  sentence of each chunk), YouTube transcripts (the unofficial library is often blocked from cloud IPs;
  pasted text is the fallback), HTML extraction on arbitrary sites, very large PDFs, and the webhook
  through Caddy on a real domain.

## Phase 3: recall engine

- **FSRS via the `fsrs` package (v6), fuzzing off** so schedules are reproducible. The card state is
  stored as `review_items.fsrs_state` and `due_at` mirrors it for the index.
- **Grade mapping (section 6.3):** correct unaided = Good, or Easy when answered within 6 s of the
  question (that time includes the question being spoken, so it is generous; tune in
  `hint_ladder.EASY_WITHIN_MS`); tier 1 = Hard; tier 2 or 3 = Again.
- **Fragile rule.** Tier 3 on two consecutive reviews of the same item sets `fragile` on the item and its
  note and caps the next interval at one day (even if FSRS would schedule it later). Two consecutive
  unaided correct answers clear it. Confusion also sets `notes.fragile` (new column); the map shows
  the note as fragile, and `GET /api/graph` returns real `strength` (mean FSRS retrievability) now.
- **Skipping a question does not grade it**, so it stays due.
- **Router is rules first.** Obvious commands ("quiz me", "read me my notes on X", "explain X",
  "how does X work") match by regex with no LLM call, so they add no latency. Only a question that
  matches no rule calls the fast model's structured router. Everything else is capture. Teach-back and
  ingest review have no node yet and fall back to capture. Inside a quiz or read-back, speech is
  sticky: it is an answer or a pace command unless it matches a command word.
- **Spoken-turn nodes (explain, read_back, quiz, chitchat) run in the connection, not as LangGraph
  nodes,** because they stream speech. LangGraph still runs the capture then enrich pipeline.
- **One fast-model call grades an answer and writes the next hint** (`QuizTurn`), so a wrong answer
  costs one round trip, not two. After a tier 3 reveal the next utterance ends the question without an
  LLM call. The real latency of this has not been measured: no keys.
- **Review items are generated in `enrich`**: up to 2 per note (a cloze and a question), only if the
  note has none, and capped at 20 per session. Prompts that would ask something the note does not say
  are the model's risk; the prompt forbids it and cloze prompts are validated to have exactly one blank.
- **Confusion detection:** phrases ("I don't get it", "what do you mean", "wait" at the start, "dumb it
  down", ...), the same question twice (word-overlap 0.8), and silence after an explanation
  (`CONFUSION_SILENCE_S`, default 25 s). In a quiz a confusion phrase climbs the hint ladder instead.
- **Explanations are not filed as notes.** The assistant's explanation comes with a diagram and a
  "Save as note" button that creates an `origin='assistant'`, unconfirmed note (section 2 rule 6).
- **Read-back** orders notes by prerequisite links (cycle-safe), says one line on why each matters,
  and ends by asking a stored question, which hands over to the quiz. Pace commands change the TTS
  speed (0.7 to 1.2).
- **Hybrid retrieval** = vector similarity and full-text rank fused with reciprocal rank fusion.
- **Not built / not verified:** the real LLM prompts have not run against a real model (grading
  leniency, hint quality, extraction quality). The fake LLM grades by word overlap. Daily brief and
  stats are Phase 5. The `/review` screen reuses the session view (voice-driven) rather than a
  separate implementation.

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
