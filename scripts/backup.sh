#!/usr/bin/env bash
# Dump the production database to backups/ and keep the newest 14. Run from cron on the VM.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p backups
out="backups/recall-$(date +%F-%H%M).sql.gz"
docker compose -f docker-compose.prod.yml exec -T db \
  sh -c 'pg_dump --clean --if-exists -U "$POSTGRES_USER" "$POSTGRES_DB"' | gzip > "$out"
test -s "$out" || { echo "backup is empty" >&2; rm -f "$out"; exit 1; }
ls -1t backups/recall-*.sql.gz | tail -n +15 | xargs -r rm --
echo "wrote $out"
