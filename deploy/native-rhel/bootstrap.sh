#!/usr/bin/env bash
# Push the 10 fixture banking apps into local GitLab, register Sherlock's
# webhook on each, and trigger the first scan.
#
# Usage (after install-sherlock.sh):
#   sudo PAT_TOKEN=<token> VM_HOST=<vm-fqdn-or-ip> ./bootstrap.sh
#
# This is a thin wrapper around scripts/bootstrap-gitlab.sh + register-webhooks.sh
# in the repo root — they're already tested for the laptop demo and just need
# the right env vars to point at the local-VM GitLab.

set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "must be run as root (sudo)" >&2; exit 1; }
[[ -n "${PAT_TOKEN:-}" ]] || { echo "set PAT_TOKEN to the GitLab Personal Access Token" >&2; exit 1; }
[[ -n "${VM_HOST:-}" ]] || { echo "set VM_HOST to the VM hostname or IP" >&2; exit 1; }

SHERLOCK_HOME="${SHERLOCK_HOME:-/opt/sherlock}"
GITLAB_PORT="${GITLAB_PORT:-8080}"
SHERLOCK_PORT="${SHERLOCK_PORT:-8001}"

cd "$SHERLOCK_HOME"

# Both the bootstrap-gitlab.sh and register-webhooks.sh scripts source .env at
# the repo root for GITLAB_TOKEN / GITLAB_HOSTNAME / GITLAB_HTTP_PORT etc.
echo "==> Writing $SHERLOCK_HOME/.env"
cat > .env <<EOF
GITLAB_HOSTNAME=$VM_HOST
GITLAB_HTTP_PORT=$GITLAB_PORT
GITLAB_TOKEN=$PAT_TOKEN
GITLAB_GROUP=banking
SHERLOCK_PORT=$SHERLOCK_PORT
WEBHOOK_SECRET=$(awk -F= '/^WEBHOOK_SECRET=/{print $2}' /etc/sherlock/sherlock.env)
EOF
chown sherlock:sherlock .env

echo "==> Pushing the 10 fixture banking apps into GitLab"
./scripts/bootstrap-gitlab.sh

echo "==> Registering Sherlock webhook on each fixture repo"
./scripts/register-webhooks.sh

echo "==> Triggering first scan-all"
curl -fsS -X POST "http://localhost:$SHERLOCK_PORT/scan-all" | jq '.scanned, .results[].app' 2>/dev/null || true

echo
echo "============================================================"
echo "Done. Open the canvas at:"
echo "  http://${VM_HOST}:${SHERLOCK_PORT}/ui/"
echo
echo "Try it:"
echo "  curl 'http://localhost:${SHERLOCK_PORT}/api/impact/account-service?direction=downstream&depth=3' | jq"
echo "============================================================"
