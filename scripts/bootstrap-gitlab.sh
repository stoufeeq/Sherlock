#!/usr/bin/env bash
# Create a 'banking' group and 10 projects in GitLab, then push each
# fixtures/<name>/ directory as the initial commit on the default branch.
#
# Requires: GITLAB_TOKEN, GITLAB_HOSTNAME, GITLAB_HTTP_PORT in .env
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

: "${GITLAB_TOKEN:?set GITLAB_TOKEN in .env (create a PAT in the GitLab UI first)}"
HOST="${GITLAB_HOSTNAME:-gitlab.local}"
PORT="${GITLAB_HTTP_PORT:-8080}"
BASE="http://${HOST}:${PORT}"
API="${BASE}/api/v4"

GROUP_PATH="banking"
GROUP_NAME="Banking"

REPOS=(
  legacy-ledger
  shared-domain-lib
  account-service
  transaction-service
  customer-service
  notification-service
  fraud-detection
  analytics-service
  web-portal-bff
  mobile-bff
)

hdr=(-H "PRIVATE-TOKEN: ${GITLAB_TOKEN}")

wait_for_gitlab() {
  echo "Waiting for GitLab at ${BASE} ..."
  for _ in $(seq 1 60); do
    if curl -fsS "${API}/version" "${hdr[@]}" >/dev/null 2>&1; then
      echo "GitLab is up."
      return 0
    fi
    sleep 5
  done
  echo "GitLab never became ready." >&2
  exit 1
}

ensure_group() {
  local existing
  existing=$(curl -fsS "${API}/groups/${GROUP_PATH}" "${hdr[@]}" || true)
  if [[ -n "${existing}" && "${existing}" != *"404 Group"* ]]; then
    echo "Group '${GROUP_PATH}' already exists."
    return
  fi
  echo "Creating group '${GROUP_PATH}'..."
  curl -fsS -X POST "${API}/groups" "${hdr[@]}" \
    --data "name=${GROUP_NAME}&path=${GROUP_PATH}&visibility=internal" >/dev/null
}

project_id() {
  local name="$1"
  local encoded="${GROUP_PATH}%2F${name}"
  curl -fsS "${API}/projects/${encoded}" "${hdr[@]}" 2>/dev/null | \
    python3 -c 'import json,sys;d=json.load(sys.stdin);print(d.get("id",""))' 2>/dev/null || echo ""
}

ensure_project() {
  local name="$1"
  local pid
  pid=$(project_id "${name}")
  if [[ -n "${pid}" ]]; then
    echo "Project '${GROUP_PATH}/${name}' exists (id=${pid})."
    return
  fi
  echo "Creating project '${GROUP_PATH}/${name}'..."
  local group_id
  group_id=$(curl -fsS "${API}/groups/${GROUP_PATH}" "${hdr[@]}" | \
    python3 -c 'import json,sys;print(json.load(sys.stdin)["id"])')
  curl -fsS -X POST "${API}/projects" "${hdr[@]}" \
    --data "name=${name}&path=${name}&namespace_id=${group_id}&visibility=internal&initialize_with_readme=false" \
    >/dev/null
}

push_fixture() {
  local name="$1"
  local dir="fixtures/${name}"
  local remote="http://oauth2:${GITLAB_TOKEN}@${HOST}:${PORT}/${GROUP_PATH}/${name}.git"

  echo "Pushing ${name} ..."
  (
    cd "${dir}"
    if [[ ! -d .git ]]; then
      git init -q -b main
      git add .
      git -c user.email=bootstrap@sherlock.local -c user.name=Sherlock \
        commit -q -m "initial: scaffold ${name}"
    fi
    git remote remove origin >/dev/null 2>&1 || true
    git remote add origin "${remote}"
    git push -u origin main --force-with-lease >/dev/null
  )
}

main() {
  wait_for_gitlab
  ensure_group
  for r in "${REPOS[@]}"; do ensure_project "$r"; done
  for r in "${REPOS[@]}"; do push_fixture "$r"; done
  echo ""
  echo "Done. Visit ${BASE}/${GROUP_PATH}"
}

main "$@"
