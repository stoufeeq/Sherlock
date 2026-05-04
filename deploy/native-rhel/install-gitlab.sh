#!/usr/bin/env bash
# Install GitLab CE Omnibus natively on RHEL 8/9.
#
# Usage:
#   sudo VM_HOST=<vm-fqdn-or-ip> ./install-gitlab.sh
#
# After this finishes:
#   1. Visit http://$VM_HOST:8080
#   2. Log in as `root` with the printed initial password
#   3. Create a Personal Access Token (api + write_repository scopes)
#   4. Run install-sherlock.sh next

set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "must be run as root (sudo)" >&2; exit 1; }
[[ -n "${VM_HOST:-}" ]] || { echo "set VM_HOST to the VM hostname or IP (e.g. sherlock-poc.ubs.local)" >&2; exit 1; }

GITLAB_PORT="${GITLAB_PORT:-8080}"
EXTERNAL_URL="http://${VM_HOST}:${GITLAB_PORT}"

echo "==> Adding GitLab CE rpm repo"
curl -fsSL https://packages.gitlab.com/install/repositories/gitlab/gitlab-ce/script.rpm.sh | bash

echo "==> Installing gitlab-ce (this is the slow step — first reconfigure takes ~5 min)"
EXTERNAL_URL="$EXTERNAL_URL" dnf -y install gitlab-ce

# Match the laptop demo's compose tweak: move Puma off :8080 so it doesn't
# collide with nginx. Without this, GitLab crash-loops on EADDRINUSE.
echo "==> Tightening gitlab.rb (Puma port + memory caps for an 8-16GB VM)"
cat >> /etc/gitlab/gitlab.rb <<EOF

# Sherlock POC overrides — keeps Puma off :8080 so nginx can have it
puma['port'] = 8081
puma['worker_processes'] = 2
sidekiq['max_concurrency'] = 10
prometheus_monitoring['enable'] = false
EOF

echo "==> Reconfiguring GitLab (~3-5 min)"
gitlab-ctl reconfigure >/dev/null

echo "==> Opening firewalld for GitLab ports"
firewall-cmd --permanent --add-port=${GITLAB_PORT}/tcp
firewall-cmd --permanent --add-port=2222/tcp || true   # GitLab SSH (optional)
firewall-cmd --reload

INITIAL_PASSWORD_FILE=/etc/gitlab/initial_root_password
echo
echo "============================================================"
echo "GitLab is up at:  ${EXTERNAL_URL}"
echo
if [[ -f "$INITIAL_PASSWORD_FILE" ]]; then
  echo "Initial root password (file is auto-deleted after 24h):"
  echo
  grep '^Password:' "$INITIAL_PASSWORD_FILE" || cat "$INITIAL_PASSWORD_FILE"
else
  echo "$INITIAL_PASSWORD_FILE not found — reset via:"
  echo "  sudo gitlab-rake \"gitlab:password:reset\""
fi
echo
echo "Next steps:"
echo "  1. Log in to ${EXTERNAL_URL} as 'root' with the password above"
echo "  2. User menu (top-right) -> Edit profile -> Access Tokens"
echo "  3. Create a token: scopes = api, write_repository (90 days is fine)"
echo "  4. Save it, then run:"
echo "       sudo PAT_TOKEN=<token> VM_HOST=${VM_HOST} ./install-sherlock.sh"
echo "============================================================"
