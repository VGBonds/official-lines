#!/usr/bin/env bash
# Copy the code from your laptop to the server and install dependencies there.
# Your data, .env and generated site on the server are never touched.
#   deploy/push.sh <server-ip-or-domain>
set -euo pipefail

SERVER="${1:?usage: deploy/push.sh <server-ip-or-domain>}"
cd "$(dirname "$0")/.."

rsync -az --delete \
  --exclude .git --exclude .venv --exclude /data --exclude /site --exclude .env \
  --exclude __pycache__ --exclude .pytest_cache --exclude .ruff_cache --exclude .idea \
  ./ "parallax@$SERVER:parallax/"

ssh "parallax@$SERVER" 'cd parallax && ~/.local/bin/uv sync --frozen --no-dev'
echo "Code updated on $SERVER. The next scheduled run uses it."
