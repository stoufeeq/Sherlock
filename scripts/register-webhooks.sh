#!/usr/bin/env bash
# Register Sherlock's /webhooks/gitlab URL on every fixture project, and
# enable GitLab's 'allow_local_requests_from_web_hooks_and_services' setting
# (without which webhooks to container hostnames get blocked).
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

: "${GITLAB_TOKEN:?set GITLAB_TOKEN in .env}"
HOST="${GITLAB_HOSTNAME:-localhost}"
PORT="${GITLAB_HTTP_PORT:-8080}"
BASE="http://${HOST}:${PORT}"
API="${BASE}/api/v4"
SECRET="${WEBHOOK_SECRET:-sherlock-local-dev}"
GROUP="${GITLAB_GROUP:-banking}"
WEBHOOK_URL="http://sherlock:8000/webhooks/gitlab"

hdr=(-H "PRIVATE-TOKEN: ${GITLAB_TOKEN}")

echo "Enabling allow_local_requests_from_web_hooks_and_services..."
curl -fsS -X PUT "${API}/application/settings" "${hdr[@]}" \
  --data "allow_local_requests_from_web_hooks_and_services=true" >/dev/null

echo "Fetching projects in group '${GROUP}'..."
projects=$(curl -fsS "${API}/groups/${GROUP}/projects?per_page=100" "${hdr[@]}")

project_ids=$(echo "${projects}" | python3 -c '
import json, sys
for p in json.load(sys.stdin):
    print(p["id"], p["path"])
')

while IFS= read -r line; do
  pid=$(echo "$line" | awk "{print \$1}")
  name=$(echo "$line" | awk "{print \$2}")

  existing=$(curl -fsS "${API}/projects/${pid}/hooks" "${hdr[@]}")
  has=$(echo "${existing}" | python3 -c "
import json, sys
hooks = json.load(sys.stdin)
print('yes' if any(h.get('url') == '${WEBHOOK_URL}' for h in hooks) else 'no')
")
  if [[ "${has}" == "yes" ]]; then
    echo "[skip] ${name} already has webhook"
    continue
  fi
  echo "[add]  ${name}"
  curl -fsS -X POST "${API}/projects/${pid}/hooks" "${hdr[@]}" \
    --data-urlencode "url=${WEBHOOK_URL}" \
    --data-urlencode "token=${SECRET}" \
    --data "push_events=true&merge_requests_events=true&enable_ssl_verification=false" \
    >/dev/null
done <<< "${project_ids}"

echo ""
echo "Done. Webhooks point at ${WEBHOOK_URL}"
