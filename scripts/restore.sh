#!/usr/bin/env bash
# Restore a backup into the production database: scripts/restore.sh backups/recall-DATE.sql.gz
set -euo pipefail
cd "$(dirname "$0")/.."
file="${1:?usage: restore.sh backups/recall-DATE.sql.gz}"
read -r -p "This overwrites the current database with $file. Type 'yes' to continue: " ok
[ "$ok" = "yes" ] || exit 1
gunzip -c "$file" | docker compose -f docker-compose.prod.yml exec -T db \
  sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" "$POSTGRES_DB"'
