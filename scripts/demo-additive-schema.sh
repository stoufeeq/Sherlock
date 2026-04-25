#!/usr/bin/env bash
# Demo: account-service adds an OPTIONAL response field to /accounts/{id}/balance.
# Expected Sherlock output: 'endpoint_schema_extended' (info-level, NON-breaking) —
# NOT 'endpoint_schema_changed' (breaking). Demonstrates required-vs-optional
# decomposition of the schema fingerprint.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"
[[ -f .env ]] && { set -a; source .env; set +a; }

: "${GITLAB_TOKEN:?set GITLAB_TOKEN in .env}"
HOST="${GITLAB_HOSTNAME:-localhost}"; PORT="${GITLAB_HTTP_PORT:-8080}"
GROUP="${GITLAB_GROUP:-banking}"
API="http://${HOST}:${PORT}/api/v4"
CLONE="http://oauth2:${GITLAB_TOKEN}@${HOST}:${PORT}/${GROUP}/account-service.git"
BRANCH="demo/add-optional-balance-field-$(date +%s)"

hdr=(-H "PRIVATE-TOKEN: ${GITLAB_TOKEN}")
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT

echo "[1/5] clone account-service"
git clone -q "${CLONE}" "${tmp}/account-service"
cd "${tmp}/account-service"
git checkout -q -b "${BRANCH}"

echo "[2/5] add optional 'lastModifiedAt' field to Balance schema"
python3 - <<'PY'
import yaml, pathlib
p = pathlib.Path("openapi.yaml")
spec = yaml.safe_load(p.read_text())
balance = spec["components"]["schemas"]["Balance"]
# Add an OPTIONAL property — note we do NOT add it to the `required` list
balance.setdefault("properties", {})["lastModifiedAt"] = {
    "type": "string", "format": "date-time",
    "description": "Optional — when the balance was last reconciled (added 2026-04)."
}
p.write_text(yaml.safe_dump(spec, sort_keys=False))
print("added optional field; required list unchanged")
PY

git -c user.email=demo@sherlock.local -c user.name="Sherlock Demo" \
  commit -qam "feat: add optional lastModifiedAt to Balance response (additive)"
git push -q origin "${BRANCH}"

echo "[3/5] open MR"
PID=$(curl -fsS "${API}/projects/${GROUP}%2Faccount-service" "${hdr[@]}" | python3 -c 'import json,sys;print(json.load(sys.stdin)["id"])')
MR_IID=$(curl -fsS -X POST "${API}/projects/${PID}/merge_requests" "${hdr[@]}" \
  --data-urlencode "source_branch=${BRANCH}" \
  --data-urlencode "target_branch=main" \
  --data-urlencode "title=[demo] add optional lastModifiedAt field to Balance" | \
  python3 -c 'import json,sys;print(json.load(sys.stdin)["iid"])')
MR_URL="http://${HOST}:${PORT}/${GROUP}/account-service/-/merge_requests/${MR_IID}"
echo "    MR !${MR_IID}  ${MR_URL}"

echo "[4/5] trigger Sherlock analysis"
curl -fsS -X POST "http://localhost:${SHERLOCK_PORT:-8001}/analyze-mr" \
  -H 'Content-Type: application/json' \
  -d "{\"app_name\":\"account-service\",\"mr_iid\":${MR_IID},\"source_branch\":\"${BRANCH}\"}" \
  > /tmp/sherlock-additive.json

echo "[5/5] result"
python3 <<'PY'
import json
d = json.load(open("/tmp/sherlock-additive.json"))
print(f"  source commit: {d['source_commit'][:12]}")
print(f"  breaks: {len(d['breaks'])}")
for b in d['breaks']:
    print(f"    - {b['kind']:<32} {b['detail']}")
print()
print("EXPECTED:")
print("    - endpoint_schema_extended       GET /accounts/{*}/balance")
print("                                      (info — non-breaking)")
print("    NO 'endpoint_schema_changed' on this endpoint.")
PY

echo
echo "Inspect:  ${MR_URL}"
