#!/usr/bin/env bash
# Nightly backup via the server API (safe while running).
# Usage: GAMNET_TOKEN=<owner-token> ./deploy/backup.sh [http://127.0.0.1:8000]
set -euo pipefail

SERVER="${1:-http://127.0.0.1:8000}"
: "${GAMNET_TOKEN:?set GAMNET_TOKEN to an owner/operator token with backup.manage}"

curl -sS -X POST "$SERVER/api/v1/admin/backups" \
  -H "Authorization: Bearer $GAMNET_TOKEN" \
  -H "Content-Type: application/json" -d '{}'
echo
