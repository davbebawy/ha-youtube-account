#!/bin/bash
# live_probe.sh: run this checkout's youtube.py on the HA box against the stored
# YouTube account cookies, read-only, and print a summary (no cookies, no secrets).
#   live_probe.sh feed | watch_later
# Use it before and after a parser change: YouTube's page shape is the thing that
# breaks. Never add a write call (add/remove/mark) here.
set -euo pipefail
cd "$(dirname "$0")"
WHAT=${1:-feed}
MOD=$(base64 < ../custom_components/youtube_account/youtube.py | tr -d '\n')
{ echo "import base64"; echo "SRC = base64.b64decode('$MOD').decode()"; echo "WHAT = '$WHAT'"; cat live_probe.py; } \
  | ssh home-assistant "sudo docker exec -i homeassistant python3 -" 2>&1 \
  | python3 ~/.claude/hooks/redact-secrets.py
