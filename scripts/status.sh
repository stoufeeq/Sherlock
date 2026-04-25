#!/usr/bin/env bash
# List fixture projects currently present in the local GitLab.
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

curl -fsS "${API}/groups/banking/projects?per_page=50" \
  -H "PRIVATE-TOKEN: ${GITLAB_TOKEN}" | \
  python3 -c '
import json, sys
rows = json.load(sys.stdin)
if not rows:
    print("No projects found in banking group.")
    sys.exit(0)
print("%-22s %-16s %s" % ("NAME", "DEFAULT BRANCH", "CLONE URL"))
for p in rows:
    name = p["path"]
    branch = p.get("default_branch") or "-"
    url = p["http_url_to_repo"]
    print("%-22s %-16s %s" % (name, branch, url))
'
