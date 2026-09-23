#!/usr/bin/env bash
# GameNet Pro production install (Ubuntu/Debian).
# Usage: sudo ./deploy/install.sh [/opt/gamnet-ai-pro]
set -euo pipefail

DEST="${1:-/opt/gamnet-ai-pro}"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"

id gamenet >/dev/null 2>&1 || useradd --system --home "$DEST" --shell /usr/sbin/nologin gamenet
mkdir -p "$DEST" /var/lib/gamenet
cp -r "$REPO_DIR"/. "$DEST"/
cd "$DEST"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e .
chown -R gamenet:gamenet "$DEST" /var/lib/gamenet
cp deploy/gamenet-server.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now gamenet-server.service
echo "GameNet installed at $DEST; service gamenet-server started."
