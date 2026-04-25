#!/usr/bin/env bash
# Create an MR against one of the fixture repos that deliberately removes the
# GET /accounts/{id} endpoint from account-service's OpenAPI spec.
#
# Expected result: Sherlock analyzes the MR and posts a comment listing every
# upstream caller (transaction-service, fraud-detection, mobile-bff, web-portal-bff).
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
GROUP="${GITLAB_GROUP:-banking}"
API="http://${HOST}:${PORT}/api/v4"
CLONE_URL="http://oauth2:${GITLAB_TOKEN}@${HOST}:${PORT}/${GROUP}/account-service.git"
BRANCH="demo/remove-account-endpoint-$(date +%s)"

hdr=(-H "PRIVATE-TOKEN: ${GITLAB_TOKEN}")
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

echo "[1/5] clone account-service"
git clone -q "${CLONE_URL}" "${tmp}/account-service"
cd "${tmp}/account-service"
git checkout -q -b "${BRANCH}"

echo "[2/5] remove GET /accounts/{id} from openapi.yaml"
python3 - <<'PY'
import yaml, pathlib
p = pathlib.Path("openapi.yaml")
spec = yaml.safe_load(p.read_text())
removed = spec["paths"].pop("/accounts/{id}", None)
assert removed is not None, "endpoint not present"
p.write_text(yaml.safe_dump(spec, sort_keys=False))
print("removed", list(removed.keys()))
PY

git -c user.email=demo@sherlock.local -c user.name="Sherlock Demo" \
  commit -qam "chore: drop GET /accounts/{id} for demo"
git push -q origin "${BRANCH}"

echo "[3/5] resolve project id"
PID=$(curl -fsS "${API}/projects/${GROUP}%2Faccount-service" "${hdr[@]}" | \
  python3 -c 'import json,sys;print(json.load(sys.stdin)["id"])')

echo "[4/5] open MR against main"
MR_IID=$(curl -fsS -X POST "${API}/projects/${PID}/merge_requests" "${hdr[@]}" \
  --data-urlencode "source_branch=${BRANCH}" \
  --data-urlencode "target_branch=main" \
  --data-urlencode "title=[demo] remove account endpoint" \
  --data-urlencode "description=Deliberate breaking change for Sherlock impact demo" | \
  python3 -c 'import json,sys;print(json.load(sys.stdin)["iid"])')

echo "[5/5] MR !${MR_IID} created"
echo "URL: http://${HOST}:${PORT}/${GROUP}/account-service/-/merge_requests/${MR_IID}"
echo ""
echo "Wait ~5s for the webhook to fire, then reload the MR — Sherlock should have commented."
echo "Or trigger the analysis directly:"
echo ""
echo "  curl -X POST http://localhost:\${SHERLOCK_PORT:-8001}/analyze-mr \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -d '{\"app_name\":\"account-service\",\"mr_iid\":${MR_IID},\"source_branch\":\"${BRANCH}\"}'"
