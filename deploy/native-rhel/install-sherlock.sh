#!/usr/bin/env bash
# Install Sherlock + Neo4j + CMDB stub natively on RHEL 8/9.
# Idempotent — safe to re-run if a step fails partway through.
#
# Usage (after install-gitlab.sh + a PAT created in the GitLab UI):
#   sudo PAT_TOKEN=<token> VM_HOST=<vm-fqdn-or-ip> ./install-sherlock.sh
#
# Optional env knobs:
#   SHERLOCK_HOME      install root             default /opt/sherlock
#   NEO4J_PASSWORD     initial graph password   default sherlock-dev
#   PIP_INDEX_URL      internal PyPI proxy URL  default pypi.org
#                      (e.g. https://artifactory.ubs.internal/api/pypi/pypi/simple/)
#   PIP_TRUSTED_HOST   bypass TLS verify for the PyPI host (corporate self-signed certs)
#                      (e.g. artifactory.ubs.internal)
#   OFFLINE_RPM_DIR    directory containing pre-downloaded gitlab-ce / neo4j RPMs
#                      (e.g. /root/sherlock-rpms — used when those repos aren't reachable)

set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "must be run as root (sudo)" >&2; exit 1; }
[[ -n "${PAT_TOKEN:-}" ]] || { echo "set PAT_TOKEN to the GitLab Personal Access Token" >&2; exit 1; }
[[ -n "${VM_HOST:-}" ]] || { echo "set VM_HOST to the VM hostname or IP" >&2; exit 1; }

SHERLOCK_HOME="${SHERLOCK_HOME:-/opt/sherlock}"
NEO4J_PASSWORD="${NEO4J_PASSWORD:-sherlock-dev}"
WEBHOOK_SECRET="${WEBHOOK_SECRET:-$(openssl rand -hex 32)}"
DEPLOY_DIR="$(cd "$(dirname "$0")" && pwd)"

# Build pip extra-flags from PIP_INDEX_URL / PIP_TRUSTED_HOST. Empty array
# when neither is set so the call sites stay clean.
PIP_OPTS=()
if [[ -n "${PIP_INDEX_URL:-}" ]]; then
  PIP_OPTS+=(--index-url "$PIP_INDEX_URL")
fi
if [[ -n "${PIP_TRUSTED_HOST:-}" ]]; then
  PIP_OPTS+=(--trusted-host "$PIP_TRUSTED_HOST")
fi

# 1. OS prereqs ---------------------------------------------------------------
echo "==> Installing OS prerequisites"
dnf -y install python3.12 python3.12-pip python3.12-devel \
                git curl jq policycoreutils-python-utils openssl

# 2. Neo4j --------------------------------------------------------------------
if rpm -q neo4j >/dev/null 2>&1; then
  echo "==> Neo4j already installed (skipping)"
elif [[ -n "${OFFLINE_RPM_DIR:-}" ]] && ls "$OFFLINE_RPM_DIR"/neo4j-*.rpm >/dev/null 2>&1; then
  echo "==> Installing Neo4j from offline RPM at $OFFLINE_RPM_DIR"
  # cypher-shell is a dependency on most Neo4j RPMs — pull it in too if present
  dnf -y install "$OFFLINE_RPM_DIR"/cypher-shell-*.rpm "$OFFLINE_RPM_DIR"/neo4j-*.rpm 2>/dev/null \
    || dnf -y install "$OFFLINE_RPM_DIR"/neo4j-*.rpm
  neo4j-admin dbms set-initial-password "$NEO4J_PASSWORD" || true
else
  echo "==> Adding Neo4j rpm repo + installing from yum.neo4j.com"
  rpm --import https://debian.neo4j.com/neotechnology.gpg.key
  cat >/etc/yum.repos.d/neo4j.repo <<'REPO'
[neo4j]
name=Neo4j RPM Repository
baseurl=https://yum.neo4j.com/stable/5
enabled=1
gpgcheck=1
REPO
  dnf -y install neo4j
  neo4j-admin dbms set-initial-password "$NEO4J_PASSWORD" || true
fi
systemctl enable --now neo4j

# 3. Sherlock user + repo + venv ---------------------------------------------
if ! id sherlock >/dev/null 2>&1; then
  useradd --system --home "$SHERLOCK_HOME" --shell /sbin/nologin sherlock
fi

# Source can arrive three ways: git clone (if VM has github.com access), an
# unzipped GitHub release (no .git dir), or a pre-existing checkout. Handle all
# three without forcing internet to github when a zip-extracted source already
# exists.
if [[ -d "$SHERLOCK_HOME/services/sherlock" ]]; then
  if [[ -d "$SHERLOCK_HOME/.git" ]]; then
    echo "==> $SHERLOCK_HOME is a git checkout — pulling latest"
    git -C "$SHERLOCK_HOME" pull --ff-only || \
      echo "    (pull failed — proceeding with the source as-is)"
  else
    echo "==> Using existing source at $SHERLOCK_HOME (zip-extracted, no git)"
  fi
elif [[ ! -e "$SHERLOCK_HOME" ]]; then
  echo "==> Cloning Sherlock to $SHERLOCK_HOME"
  git clone https://github.com/stoufeeq/Sherlock.git "$SHERLOCK_HOME"
else
  echo "ERROR: $SHERLOCK_HOME exists but doesn't contain Sherlock source." >&2
  echo "       Either delete it, or unzip the Sherlock release into it first:" >&2
  echo "         sudo unzip Sherlock-main.zip -d /opt && sudo mv /opt/Sherlock-main $SHERLOCK_HOME" >&2
  exit 1
fi

echo "==> Building Sherlock venv (pip index: ${PIP_INDEX_URL:-pypi.org default})"
python3.12 -m venv "$SHERLOCK_HOME/venv"
"$SHERLOCK_HOME/venv/bin/pip" install "${PIP_OPTS[@]}" --upgrade pip
"$SHERLOCK_HOME/venv/bin/pip" install "${PIP_OPTS[@]}" -r "$SHERLOCK_HOME/services/sherlock/requirements.txt"

echo "==> Building CMDB-stub venv"
python3.12 -m venv "$SHERLOCK_HOME/cmdb-venv"
"$SHERLOCK_HOME/cmdb-venv/bin/pip" install "${PIP_OPTS[@]}" --upgrade pip
"$SHERLOCK_HOME/cmdb-venv/bin/pip" install "${PIP_OPTS[@]}" -r "$SHERLOCK_HOME/services/sherlock-cmdb-stub/requirements.txt"

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
# Templates use @SHERLOCK_HOME@ so a non-default install root (e.g. /app/C10/Sherlock)
# is honoured in WorkingDirectory + ExecStart, not just in pip install paths.
echo "==> Installing systemd units (rendered with SHERLOCK_HOME=$SHERLOCK_HOME)"
sed "s|@SHERLOCK_HOME@|$SHERLOCK_HOME|g" \
    "$DEPLOY_DIR/systemd/sherlock.service"  > /etc/systemd/system/sherlock.service
sed "s|@SHERLOCK_HOME@|$SHERLOCK_HOME|g" \
    "$DEPLOY_DIR/systemd/cmdb-stub.service" > /etc/systemd/system/cmdb-stub.service
chmod 0644 /etc/systemd/system/sherlock.service /etc/systemd/system/cmdb-stub.service
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
