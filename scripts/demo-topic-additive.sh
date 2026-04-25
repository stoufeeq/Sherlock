#!/usr/bin/env bash
# Demo: transaction-service adds an OPTIONAL field 'traceId' to the
# banking.transactions.created event payload. Expected Sherlock output:
# 'topic_payload_extended' (info-level, NON-breaking) — NOT 'topic_payload_changed'
# (breaking). Demonstrates required-vs-optional decomposition for AsyncAPI.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"
[[ -f .env ]] && { set -a; source .env; set +a; }

: "${GITLAB_TOKEN:?set GITLAB_TOKEN in .env}"
HOST="${GITLAB_HOSTNAME:-localhost}"; PORT="${GITLAB_HTTP_PORT:-8080}"
GROUP="${GITLAB_GROUP:-banking}"
API="http://${HOST}:${PORT}/api/v4"
CLONE="http://oauth2:${GITLAB_TOKEN}@${HOST}:${PORT}/${GROUP}/transaction-service.git"
BRANCH="demo/add-optional-traceid-$(date +%s)"

hdr=(-H "PRIVATE-TOKEN: ${GITLAB_TOKEN}")
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT

echo "[1/5] clone transaction-service"
git clone -q "${CLONE}" "${tmp}/transaction-service"
cd "${tmp}/transaction-service"
git checkout -q -b "${BRANCH}"

echo "[2/5] add optional 'traceId' to TransactionCreatedEvent payload"
python3 - <<'PY'
import yaml, pathlib
p = pathlib.Path("asyncapi.yaml")
spec = yaml.safe_load(p.read_text())
payload = spec["channels"]["banking.transactions.created"]["publish"]["message"]["payload"]
# Add an OPTIONAL property — note we do NOT add it to the `required` list
payload.setdefault("properties", {})["traceId"] = {
    "type": "string",
    "description": "Optional — distributed-trace correlation id (added 2026-04)."
}
p.write_text(yaml.safe_dump(spec, sort_keys=False))
print("added optional field; required list unchanged:", payload.get("required"))
PY

git -c user.email=demo@sherlock.local -c user.name="Sherlock Demo" \
  commit -qam "feat: add optional traceId to TransactionCreatedEvent (additive)"
git push -q origin "${BRANCH}"

echo "[3/5] open MR"
PID=$(curl -fsS "${API}/projects/${GROUP}%2Ftransaction-service" "${hdr[@]}" | python3 -c 'import json,sys;print(json.load(sys.stdin)["id"])')
MR_IID=$(curl -fsS -X POST "${API}/projects/${PID}/merge_requests" "${hdr[@]}" \
  --data-urlencode "source_branch=${BRANCH}" \
  --data-urlencode "target_branch=main" \
  --data-urlencode "title=[demo] add optional traceId field to TransactionCreated event" | \
  python3 -c 'import json,sys;print(json.load(sys.stdin)["iid"])')
MR_URL="http://${HOST}:${PORT}/${GROUP}/transaction-service/-/merge_requests/${MR_IID}"
echo "    MR !${MR_IID}  ${MR_URL}"

echo "[4/5] trigger Sherlock analysis"
curl -fsS -X POST "http://localhost:${SHERLOCK_PORT:-8001}/analyze-mr" \
  -H 'Content-Type: application/json' \
  -d "{\"app_name\":\"transaction-service\",\"mr_iid\":${MR_IID},\"source_branch\":\"${BRANCH}\"}" \
  > /tmp/sherlock-topic-additive.json

echo "[5/5] result"
python3 <<'PY'
import json
d = json.load(open("/tmp/sherlock-topic-additive.json"))
print(f"  source commit: {d['source_commit'][:12]}")
print(f"  breaks: {len(d['breaks'])}")
for b in d['breaks']:
    print(f"    - {b['kind']:<32} {b['detail']}")
print()
print("EXPECTED:")
print("    - topic_payload_extended         banking.transactions.created")
print("                                      (info — non-breaking)")
print("    NO 'topic_payload_changed' — the required field set is unchanged.")
PY

echo
echo "Inspect:  ${MR_URL}"
