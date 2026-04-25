#!/usr/bin/env bash
# Restore the per-fixture .git directories by re-cloning from the local GitLab.
# Use this after pushing the project to an external git remote that requires
# the inner .git directories to have been removed.
#
# Idempotent: skips fixtures that already have .git in place.
# Tolerant: warns and continues if a project is not reachable in local GitLab.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"
[[ -f .env ]] && { set -a; source .env; set +a; }

: "${GITLAB_TOKEN:?set GITLAB_TOKEN in .env}"
HOST="${GITLAB_HOSTNAME:-localhost}"
PORT="${GITLAB_HTTP_PORT:-8080}"
GROUP="${GITLAB_GROUP:-banking}"

restored=0
skipped=0
missing=0

for dir in fixtures/*/; do
  name=$(basename "$dir")
  if [[ -d "$dir/.git" ]]; then
    skipped=$((skipped + 1))
    continue
  fi

  # Probe GitLab for the project. If the local fixture was previously renamed
  # in GitLab, the user will need to clone from the new path manually.
  http_code=$(curl -s -o /dev/null -w '%{http_code}' \
    -H "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
    "http://${HOST}:${PORT}/api/v4/projects/${GROUP}%2F${name}")
  if [[ "${http_code}" != "200" ]]; then
    echo "  skip:    ${name} (not in GitLab — HTTP ${http_code})"
    missing=$((missing + 1))
    continue
  fi

  clone_url="http://oauth2:${GITLAB_TOKEN}@${HOST}:${PORT}/${GROUP}/${name}.git"
  tmp=$(mktemp -d)
  if git clone -q "${clone_url}" "${tmp}/repo" 2>/dev/null; then
    mv "${tmp}/repo/.git" "${dir}/.git"
    # Restore the remote URL with the token (clone embeds it; that's intentional
    # so subsequent `git push` from inside the fixture just works).
    rm -rf "${tmp}"
    echo "  restored: ${name}"
    restored=$((restored + 1))
  else
    rm -rf "${tmp}"
    echo "  FAILED:  ${name} (clone error)"
    missing=$((missing + 1))
  fi
done

echo
echo "summary:  restored=${restored}  already-had-git=${skipped}  missing=${missing}"
