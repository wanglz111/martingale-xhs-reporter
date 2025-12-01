#!/bin/sh
set -e

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

python xhs_summary.py --state-file "$STATE_FILE"
