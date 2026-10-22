#!/usr/bin/env bash
# Load the workflows in n8n/workflows into the running n8n container and activate them.
# n8n (regular mode) only picks up published workflows on start, so this restarts it.
set -euo pipefail
cd "$(dirname "$0")/.."
COMPOSE=("docker" "compose" "-f" "${COMPOSE_FILE:-docker-compose.yml}")
"${COMPOSE[@]}" exec -T n8n n8n import:workflow --separate --input=/workflows
for id in $(python3 -c "import json,glob;print(' '.join(json.load(open(f))['id'] for f in sorted(glob.glob('n8n/workflows/*.json'))))"); do
  "${COMPOSE[@]}" exec -T n8n n8n publish:workflow --id="$id"
done
"${COMPOSE[@]}" restart n8n
echo "n8n restarted with the Recall workflows active."
