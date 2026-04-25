#!/usr/bin/env bash
# Demo: account-service removes /accounts/{id}/legacy-status — which was already
# marked `deprecated: true` in main. Expected Sherlock output:
# 'deprecated_endpoint_removed' (info-level, low severity) — NOT
# 'endpoint_removed' (full breaking-change). Demonstrates deprecation awareness.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"
[[ -f .env ]] && { set -a; source .env; set +a; }

: "${GITLAB_TOKEN:?set GITLAB_TOKEN in .env}"
HOST="${GITLAB_HOSTNAME:-localhost}"; PORT="${GITLAB_HTTP_PORT:-8080}"
GROUP="${GITLAB_GROUP:-banking}"
API="http://${HOST}:${PORT}/api/v4"
CLONE="http://oauth2:${GITLAB_TOKEN}@${HOST}:${PORT}/${GROUP}/account-service.git"
BRANCH="demo/drop-legacy-status-$(date +%s)"

hdr=(-H "PRIVATE-TOKEN: ${GITLAB_TOKEN}")
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT

echo "[1/5] clone account-service"
git clone -q "${CLONE}" "${tmp}/account-service"
cd "${tmp}/account-service"
git checkout -q -b "${BRANCH}"

echo "[2/5] remove the deprecated /accounts/{id}/legacy-status endpoint"
python3 - <<'PY'
import yaml, pathlib
p = pathlib.Path("openapi.yaml")
spec = yaml.safe_load(p.read_text())
removed = spec["paths"].pop("/accounts/{id}/legacy-status", None)
if removed is None:
    raise SystemExit("ERROR: /accounts/{id}/legacy-status not present in openapi.yaml — "
                     "did you forget to push the baseline?")
spec.get("components", {}).get("schemas", {}).pop("LegacyStatus", None)
p.write_text(yaml.safe_dump(spec, sort_keys=False))
print("removed:", list(removed.keys()))
PY

git -c user.email=demo@sherlock.local -c user.name="Sherlock Demo" \
  commit -qam "chore: drop deprecated legacy-status endpoint"
git push -q origin "${BRANCH}"

echo "[3/5] open MR"
PID=$(curl -fsS "${API}/projects/${GROUP}%2Faccount-service" "${hdr[@]}" | python3 -c 'import json,sys;print(json.load(sys.stdin)["id"])')
MR_IID=$(curl -fsS -X POST "${API}/projects/${PID}/merge_requests" "${hdr[@]}" \
  --data-urlencode "source_branch=${BRANCH}" \
  --data-urlencode "target_branch=main" \
  --data-urlencode "title=[demo] drop deprecated /accounts/{id}/legacy-status" | \
  python3 -c 'import json,sys;print(json.load(sys.stdin)["iid"])')
MR_URL="http://${HOST}:${PORT}/${GROUP}/account-service/-/merge_requests/${MR_IID}"
echo "    MR !${MR_IID}  ${MR_URL}"

echo "[4/5] trigger Sherlock analysis"
curl -fsS -X POST "http://localhost:${SHERLOCK_PORT:-8001}/analyze-mr" \
  -H 'Content-Type: application/json' \
  -d "{\"app_name\":\"account-service\",\"mr_iid\":${MR_IID},\"source_branch\":\"${BRANCH}\"}" \
  > /tmp/sherlock-deprecated.json

echo "[5/5] result"
python3 <<'PY'
import json
d = json.load(open("/tmp/sherlock-deprecated.json"))
print(f"  source commit: {d['source_commit'][:12]}")
print(f"  breaks: {len(d['breaks'])}")
for b in d['breaks']:
    print(f"    - {b['kind']:<32} {b['detail']}")
print()
print("EXPECTED:")
print("    - deprecated_endpoint_removed    GET /accounts/{*}/legacy-status")
print("                                      (info — non-breaking; team announced removal in advance)")
print("    NOT 'endpoint_removed' (which would be a hard breaking change).")
PY

echo
echo "Inspect:  ${MR_URL}"
