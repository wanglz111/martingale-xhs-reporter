#!/bin/sh
set -e

# Ensure dependencies are present (handles cases where image not rebuilt)
if ! python - <<'PY' >/dev/null 2>&1
import requests  # noqa: F401
import boto3  # noqa: F401
PY
then
  echo "[info] Installing Python dependencies..."
  pip install --no-cache-dir -r /app/requirements.txt
fi

STATE_FILE="/app/state.runtime.yaml"

cat > "$STATE_FILE" <<EOF
state:
  bucket: ${STATE_BUCKET}
  endpoint_url: "${STATE_ENDPOINT_URL}"
  access_key: "${STATE_ACCESS_KEY}"
  secret_key: "${STATE_SECRET_KEY}"
  region: ${STATE_REGION:-auto}
notify:
  bark:
    server: ${BARK_SERVER:-https://api.day.app}
    key: "${BARK_KEY}"
EOF

if [ "$1" = "--loop" ]; then
  exec python scheduler.py --state-file "$STATE_FILE"
fi

# exec python xhs_summary.py --state-file "$STATE_FILE"
