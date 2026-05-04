#!/usr/bin/env bash
# Install Sherlock + Neo4j + CMDB stub natively on RHEL 8/9.
# Idempotent — safe to re-run if a step fails partway through.
#
# Usage (after install-gitlab.sh + a PAT created in the GitLab UI):
#   sudo PAT_TOKEN=<token> VM_HOST=<vm-fqdn-or-ip> ./install-sherlock.sh
#
# Optional env knobs:
#   SHERLOCK_HOME    install root           default /opt/sherlock
#   NEO4J_PASSWORD   initial graph password default sherlock-dev

set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "must be run as root (sudo)" >&2; exit 1; }
[[ -n "${PAT_TOKEN:-}" ]] || { echo "set PAT_TOKEN to the GitLab Personal Access Token" >&2; exit 1; }
[[ -n "${VM_HOST:-}" ]] || { echo "set VM_HOST to the VM hostname or IP" >&2; exit 1; }

SHERLOCK_HOME="${SHERLOCK_HOME:-/opt/sherlock}"
NEO4J_PASSWORD="${NEO4J_PASSWORD:-sherlock-dev}"
WEBHOOK_SECRET="${WEBHOOK_SECRET:-$(openssl rand -hex 32)}"
DEPLOY_DIR="$(cd "$(dirname "$0")" && pwd)"

# 1. OS prereqs ---------------------------------------------------------------
echo "==> Installing OS prerequisites"
dnf -y install python3.12 python3.12-pip python3.12-devel \
                git curl jq policycoreutils-python-utils openssl

# 2. Neo4j --------------------------------------------------------------------
if ! rpm -q neo4j >/dev/null 2>&1; then
  echo "==> Adding Neo4j rpm repo + installing"
  rpm --import https://debian.neo4j.com/neotechnology.gpg.key
  cat >/etc/yum.repos.d/neo4j.repo <<'REPO'
[neo4j]
name=Neo4j RPM Repository
baseurl=https://yum.neo4j.com/stable/5
enabled=1
gpgcheck=1
REPO
  dnf -y install neo4j
  # Initial password — only takes effect on a brand-new install
  neo4j-admin dbms set-initial-password "$NEO4J_PASSWORD" || true
else
  echo "==> Neo4j already installed (skipping)"
fi
systemctl enable --now neo4j

# 3. Sherlock user + repo + venv ---------------------------------------------
if ! id sherlock >/dev/null 2>&1; then
  useradd --system --home "$SHERLOCK_HOME" --shell /sbin/nologin sherlock
fi

if [[ ! -d "$SHERLOCK_HOME/.git" ]]; then
  echo "==> Cloning Sherlock to $SHERLOCK_HOME"
  git clone https://github.com/stoufeeq/Sherlock.git "$SHERLOCK_HOME"
else
  echo "==> $SHERLOCK_HOME already a git checkout — pulling latest"
  git -C "$SHERLOCK_HOME" pull --ff-only
fi

echo "==> Building Sherlock venv"
python3.12 -m venv "$SHERLOCK_HOME/venv"
"$SHERLOCK_HOME/venv/bin/pip" install --upgrade pip
"$SHERLOCK_HOME/venv/bin/pip" install -r "$SHERLOCK_HOME/services/sherlock/requirements.txt"

echo "==> Building CMDB-stub venv"
python3.12 -m venv "$SHERLOCK_HOME/cmdb-venv"
"$SHERLOCK_HOME/cmdb-venv/bin/pip" install --upgrade pip
"$SHERLOCK_HOME/cmdb-venv/bin/pip" install -r "$SHERLOCK_HOME/services/sherlock-cmdb-stub/requirements.txt"

# 4. /etc/sherlock config -----------------------------------------------------
echo "==> Writing /etc/sherlock/sherlock.env"
install -d -m 0750 /etc/sherlock
install -m 0644 "$SHERLOCK_HOME/services/sherlock/config/gateway-routes.yaml" \
                /etc/sherlock/gateway-routes.yaml

# Render env file from template (substitute the three variables)
sed \
  -e "s|CHANGE_ME_TO_VM_HOSTNAME|$VM_HOST|g" \
  -e "s|CHANGE_ME_TO_PAT|$PAT_TOKEN|g" \
  -e "s|CHANGE_ME_TO_RANDOM_HEX|$WEBHOOK_SECRET|g" \
  "$DEPLOY_DIR/sherlock.env.example" > /etc/sherlock/sherlock.env
chmod 0640 /etc/sherlock/sherlock.env

# Tighten ownership AFTER files are in place
chown -R sherlock:sherlock /etc/sherlock "$SHERLOCK_HOME"

# 5. systemd units ------------------------------------------------------------
echo "==> Installing systemd units"
install -m 0644 "$DEPLOY_DIR/systemd/sherlock.service"  /etc/systemd/system/sherlock.service
install -m 0644 "$DEPLOY_DIR/systemd/cmdb-stub.service" /etc/systemd/system/cmdb-stub.service
systemctl daemon-reload

# 6. Firewall -----------------------------------------------------------------
echo "==> Opening firewalld ports"
firewall-cmd --permanent --add-port=8001/tcp     # Sherlock UI/API
firewall-cmd --permanent --add-port=7474/tcp     # Neo4j Browser
firewall-cmd --permanent --add-port=8500/tcp     # CMDB stub (debug)
firewall-cmd --reload

# 7. Start services -----------------------------------------------------------
echo "==> Starting cmdb-stub + sherlock"
systemctl enable --now cmdb-stub sherlock

echo "==> Waiting for /health to come up"
for _ in $(seq 1 30); do
  if curl -fsS http://localhost:8001/health >/dev/null 2>&1; then
    echo "    Sherlock is up."
    break
  fi
  sleep 2
done

echo
echo "============================================================"
echo "Sherlock is up at:  http://${VM_HOST}:8001/ui/"
echo "Neo4j Browser at:   http://${VM_HOST}:7474/  (neo4j / $NEO4J_PASSWORD)"
echo "CMDB stub at:       http://${VM_HOST}:8500/services"
echo
echo "Next:"
echo "  sudo PAT_TOKEN=$PAT_TOKEN VM_HOST=$VM_HOST ./bootstrap.sh"
echo "  → pushes the 10 fixture banking apps into local GitLab"
echo "  → registers webhooks + triggers the first scan"
echo "============================================================"
