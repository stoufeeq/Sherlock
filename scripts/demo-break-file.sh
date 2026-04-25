#!/usr/bin/env bash
# Demo: transaction-service removes its NightlyPostingsFeedWriter → Sherlock
# should flag legacy-ledger as impacted (via READS_FILE /shared/postings/POSTINGS.DAT)
# and auto-open an impact::pending issue in the legacy-ledger repo.
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
CLONE_URL="http://oauth2:${GITLAB_TOKEN}@${HOST}:${PORT}/${GROUP}/transaction-service.git"
BRANCH="demo/drop-postings-feed-$(date +%s)"
SHERLOCK_PORT_VAL="${SHERLOCK_PORT:-8001}"

hdr=(-H "PRIVATE-TOKEN: ${GITLAB_TOKEN}")
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

echo "[1/6] clone transaction-service"
git clone -q "${CLONE_URL}" "${tmp}/transaction-service"
cd "${tmp}/transaction-service"
git checkout -q -b "${BRANCH}"

echo "[2/6] delete NightlyPostingsFeedWriter.java (the POSTINGS.DAT writer)"
rm -f src/main/java/com/sherlock/banking/transaction/NightlyPostingsFeedWriter.java
git -c user.email=demo@sherlock.local -c user.name="Sherlock Demo" \
  commit -qam "chore: drop nightly postings feed — demo"
git push -q origin "${BRANCH}"

echo "[3/6] resolve project id"
PID=$(curl -fsS "${API}/projects/${GROUP}%2Ftransaction-service" "${hdr[@]}" | \
  python3 -c 'import json,sys;print(json.load(sys.stdin)["id"])')

echo "[4/6] open MR against main"
MR_IID=$(curl -fsS -X POST "${API}/projects/${PID}/merge_requests" "${hdr[@]}" \
  --data-urlencode "source_branch=${BRANCH}" \
  --data-urlencode "target_branch=main" \
  --data-urlencode "title=[demo] drop nightly postings feed" \
  --data-urlencode "description=Deliberate file-feed break for Sherlock demo" | \
  python3 -c 'import json,sys;print(json.load(sys.stdin)["iid"])')

MR_URL="http://${HOST}:${PORT}/${GROUP}/transaction-service/-/merge_requests/${MR_IID}"
echo "[5/6] MR !${MR_IID} created: ${MR_URL}"

echo "[6/6] trigger Sherlock analysis"
curl -fsS -X POST "http://localhost:${SHERLOCK_PORT_VAL}/analyze-mr" \
  -H 'Content-Type: application/json' \
  -d "{\"app_name\":\"transaction-service\",\"mr_iid\":${MR_IID},\"source_branch\":\"${BRANCH}\"}" \
  > /tmp/sherlock-demo-break-file.json
python3 <<'PY'
import json
d = json.load(open("/tmp/sherlock-demo-break-file.json"))
print(f"\n--- Sherlock analysis for MR !{d['mr_iid']} ---")
print(f"Source commit: {d['source_commit'][:12]}   comment_posted={d['comment_posted']}   note_id={d.get('note_id')}")
print(f"Breaks detected: {len(d['breaks'])}")
for b in d['breaks']:
    print(f"\n  kind:   {b['kind']}")
    print(f"  detail: {b['detail']}")
    print(f"  impacted apps:")
    for a in b['impacted']:
        print(f"    - {a['name']:<22} team={a['team']:<20} tier={a['tier']}  on-call={a['on_call_slack']}  ({a['confidence']})")

if d.get('sticky_issues'):
    print("\n--- Sticky impact issues opened/updated ---")
    for s in d['sticky_issues']:
        print(f"  {s['app']:<22} {s['action']:<8} !{s['issue_iid']}  {s['issue_url']}")
PY

echo ""
echo "Open in browser:"
echo "  MR (top comment):        ${MR_URL}"
echo "  Impact issue on ledger:  http://${HOST}:${PORT}/${GROUP}/legacy-ledger/-/issues"
