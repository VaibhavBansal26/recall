# Deploying Recall to a cloud VM

One always-on backend holds your notes; your laptop, iPhone and iPad are all clients of it, so
they are synced by construction. Everything is served from a single HTTPS address by Caddy.

```
 laptop / iPhone / iPad (browser or installed PWA)
              │ HTTPS, one origin: https://recall.example.com
              ▼
        Caddy (auto TLS) ──► /api/*  /ws/*  /healthz ──► backend (FastAPI) ──► Postgres + pgvector
              └────────────► everything else ───────────► frontend (Next.js)
```

Only ports 80 and 443 are open. Postgres and the app containers are not reachable from outside.

## 1. What you need
- A VM: Ubuntu 24.04, 2 GB RAM, 20 GB disk is plenty (about 5 to 10 USD a month).
- A domain or subdomain you control, with an **A record** pointing at the VM's IP.
- Optional now, needed for real voice: Deepgram, ElevenLabs, Anthropic and Voyage API keys.

## 2. Prepare the VM
```bash
# firewall: SSH, HTTP, HTTPS only
sudo ufw allow OpenSSH && sudo ufw allow 80,443/tcp && sudo ufw allow 443/udp && sudo ufw enable
# Docker
curl -fsSL https://get.docker.com | sudo sh && sudo usermod -aG docker $USER   # then log out/in
git clone https://github.com/VaibhavBansal26/recall.git && cd recall
```

## 3. Configure
```bash
cp .env.prod.example .env
nano .env     # set SITE_ADDRESS, PUBLIC_ORIGIN, AUTH_PASSPHRASE, SESSION_SECRET, POSTGRES_PASSWORD
```
Generate the secrets with `openssl rand -hex 32` (SESSION_SECRET) and `openssl rand -hex 24`
(POSTGRES_PASSWORD). Pick a long passphrase: the server is on the public internet. The backend
refuses to start in production with a passphrase under 12 characters, without `COOKIE_SECURE=true`,
or without a `SESSION_SECRET`.

## 4. Start
```bash
make prod-up          # docker compose -f docker-compose.prod.yml up -d --build
make prod-logs        # wait for "Application startup complete"
curl https://recall.example.com/healthz
```
The first start takes a few minutes (image builds) and Caddy needs a minute to get the certificate.

## 5. Install on iPhone and iPad
1. Open `https://recall.example.com` in **Safari** and sign in.
2. Share button, then **Add to Home Screen**. It opens full screen like an app.
3. Allow the microphone when asked. HTTPS is what makes the mic available on iOS.

On a laptop, Chrome and Edge show an install icon in the address bar. Sessions last 30 days per
device. **Sign out** is in the top bar.

## 6. Turn on real voice
Fill the provider keys in `.env` (see the Phase 1 section of the README), set `VOICE_PROVIDER=pipeline`,
`LLM_PROVIDER=anthropic`, `EMBEDDING_PROVIDER=voyage`, then `make prod-up`.

## Backups
Your notes are only on the VM. Take backups off it too.
```bash
make backup                                   # writes backups/recall-DATE.sql.gz, keeps 14
crontab -e                                    # nightly at 03:30:
30 3 * * * cd /home/YOU/recall && ./scripts/backup.sh >> backups/cron.log 2>&1
scp YOU@vm:recall/backups/*.sql.gz ./         # copy them somewhere else regularly
./scripts/restore.sh backups/recall-DATE.sql.gz   # restore (asks for confirmation)
```
Also enable your provider's snapshot or backup feature if it has one.

## Operations
- **Update:** `git pull && make prod-up` (migrations run automatically on start).
- **Change the passphrase:** edit `AUTH_PASSPHRASE`, `make prod-up`. Change `SESSION_SECRET` too
  to sign every device out at once.
- **Brute force:** 5 wrong passphrases from one address locks it for 10 minutes.
- **Daily brief and nudge:** set `USER_TIMEZONE` and (optionally) `NUDGE_URL`, then `make n8n-import` loads
  `daily-brief-cron` (07:30) and `review-nudge` (18:00). Open Recall in the morning for the banner.
- **n8n (ingest from anywhere):** set `RECALL_SHARED_SECRET` (`openssl rand -hex 24`), then
  `docker compose -f docker-compose.prod.yml --profile n8n up -d` and `COMPOSE_FILE=docker-compose.prod.yml make n8n-import`.
  Only `https://YOUR-DOMAIN/webhook/*` is reachable from outside (through Caddy); each workflow checks the
  shared secret itself, so send `X-Recall-Secret` from your browser extension, share-sheet shortcut or
  script. The n8n editor is not published: use an SSH tunnel to reach it
  (`ssh -L 5678:$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' recall-prod-n8n-1):5678 YOU@vm`).
  Files for the inbox workflow go in `n8n/inbox/` on the VM.
- **Test the production stack on your own machine** without a domain: set
  `SITE_ADDRESS=http://localhost`, `PUBLIC_ORIGIN=http://localhost:8080`, `HTTP_PORT=8080`,
  `HTTPS_PORT=8443` in a separate env file and run
  `ENV_FILE=.env.test docker compose -f docker-compose.prod.yml --env-file .env.test up -d --build`.
  Always pass the same `ENV_FILE` on every command, or the backend is recreated with the wrong file.

## Security notes
- The app is single-user: one passphrase, one session cookie (HttpOnly, SameSite=Lax, Secure).
- The WebSocket checks the cookie and the `Origin` header.
- Your API keys live only in `.env` on the VM. Never commit it (it is git-ignored).
- Notes and voice transcripts are stored on, and sent through, a third-party VM and the AI providers
  you enable. Choose accordingly.
