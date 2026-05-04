# Native RHEL deploy — POC bundle

Single-VM, Docker-free Sherlock deploy targeting **enterprise RHEL 8/9** where
Docker isn't permitted and the corporate GitLab is RBAC-gated. Stands up:

| Component | Listens on | Role |
|---|---|---|
| GitLab CE Omnibus | `:8080` (HTTP) + `:2222` (SSH) | local GitLab, hosts the 10 fixture repos |
| Neo4j Community 5  | `:7474` + `:7687` (bolt) | Sherlock's graph store |
| Sherlock platform  | `:8001` | the FastAPI app + canvas UI |
| CMDB stub          | `:8500` | feeds team / tier / on-call / platform metadata |

Sherlock's runtime is **Postgres-free and Kafka-free** — those containers in the
laptop demo serve the *fixture apps' runtime*, which we don't run for the POC
(Sherlock only reads source code from GitLab).

---

## VM sizing

| | Minimum | Recommended |
|---|---|---|
| RAM | 8 GB (will swap during GitLab boot) | **16 GB** |
| CPU | 4 vCPU | 4–8 vCPU |
| Disk | 60 GB | **80 GB** |

GitLab Omnibus alone wants 4–8 GB resident; everything else combined is
well under 2 GB.

---

## Install — three scripts, one .env

```bash
# 1. Place the source on the VM. Either:
#    a. git clone (requires github.com access from the VM):
sudo git clone https://github.com/stoufeeq/Sherlock.git /opt/sherlock
#    b. unzip a release archive copied via SCP:
sudo unzip Sherlock-main.zip -d /opt && sudo mv /opt/Sherlock-main /opt/sherlock

cd /opt/sherlock/deploy/native-rhel

# 2. Install GitLab Omnibus (~5 min on first reconfigure)
sudo VM_HOST=<your-vm-fqdn-or-ip> ./install-gitlab.sh
# → grab the auto-generated initial root password, log in to http://<vm>:8080,
#   create a Personal Access Token (api + write_repository scopes)

# 3. Install Sherlock + Neo4j + CMDB stub (idempotent)
sudo PAT_TOKEN=<paste-the-PAT> VM_HOST=<your-vm-fqdn-or-ip> ./install-sherlock.sh

# 4. Push fixture repos into local GitLab + register webhooks + first scan
sudo PAT_TOKEN=<paste-the-PAT> VM_HOST=<your-vm-fqdn-or-ip> ./bootstrap.sh
```

**Custom install root.** All three scripts honour `SHERLOCK_HOME` if set —
e.g. if `/opt` is unwritable on your VM, use `/app/C10/Sherlock` instead:

```bash
sudo unzip Sherlock-main.zip -d /app/C10 && sudo mv /app/C10/Sherlock-main /app/C10/Sherlock
cd /app/C10/Sherlock/deploy/native-rhel
sudo SHERLOCK_HOME=/app/C10/Sherlock VM_HOST=<vm> ./install-gitlab.sh
sudo SHERLOCK_HOME=/app/C10/Sherlock PAT_TOKEN=<pat> VM_HOST=<vm> ./install-sherlock.sh
sudo SHERLOCK_HOME=/app/C10/Sherlock PAT_TOKEN=<pat> VM_HOST=<vm> ./bootstrap.sh
```

The systemd units are templated — `install-sherlock.sh` renders them with the
right `WorkingDirectory` and `ExecStart` paths automatically.

Already running as `root`? Drop the `sudo` — it's a no-op when uid=0.

After `bootstrap.sh` returns, open `http://<your-vm>:8001/ui/` — the canvas
shows the 10 fixture banking apps with their cross-app dependencies.

---

## What each script does

### `install-gitlab.sh`

- Adds the GitLab CE rpm repo, installs `gitlab-ce`, runs `gitlab-ctl reconfigure`.
- Configures `external_url` so GitLab knows what to advertise itself as.
- Moves Puma to `:8081` (matches the laptop demo to avoid the nginx-port collision).
- Prints the auto-generated initial root password.
- Pauses for you to create a Personal Access Token before the next script.

### `install-sherlock.sh`

- Installs `python3.12 git curl jq` and creates the `sherlock` system user.
- Installs Neo4j Community as an RPM, sets initial password to `sherlock-dev`.
- Builds two Python venvs (one for Sherlock, one for the CMDB stub), `pip install`s
  from the existing `requirements.txt` files.
- Installs `/etc/sherlock/sherlock.env` from the env template.
- Installs the two systemd units (`sherlock.service`, `cmdb-stub.service`).
- Opens firewall ports 8001/8080/7474/8500.
- `systemctl enable --now neo4j cmdb-stub sherlock` and waits for `/health`.

### `bootstrap.sh`

- Runs the existing `scripts/bootstrap-gitlab.sh` (creates `banking` group + 10
  projects + pushes each fixture as initial commit).
- Runs the existing `scripts/register-webhooks.sh` (installs the Sherlock
  webhook on each repo).
- Triggers a `POST /scan-all`.

---

## Verification

```bash
systemctl status neo4j cmdb-stub sherlock          # all "active (running)"
curl -s http://localhost:8001/health                # {"status":"ok",...}
curl -s http://localhost:8500/services | jq length  # 10
curl -s http://localhost:8001/api/apps | jq length  # 10

# Multi-hop blast radius
curl -s 'http://localhost:8001/api/impact/account-service?direction=downstream&depth=3' | jq
```

Browser: `http://<vm>:8001/ui/` — canvas renders, click any node, depth slider
to 3 → red→orange→amber halo per hop.

---

## SELinux

GitLab Omnibus + uvicorn don't need anything exotic, but a couple of booleans
help:

```bash
sudo setsebool -P httpd_can_network_connect on
sudo setsebool -P nis_enabled on                  # GitLab embeds a postgres
```

If the systemd units fail to start with cryptic permission errors, the
fastest diagnosis is `sudo ausearch -m avc -ts recent` — fix any AVC denials,
or `sudo setenforce 0` for the POC and re-enable later.

---

## TLS

Out of scope for the POC bundle. For pilot/production, drop nginx in front of
:8001 (Sherlock) and :8080 (GitLab) terminating against your corporate certs.
Update `GITLAB_EXTERNAL_URL` and `SHERLOCK_WEBHOOK_URL` to the `https://` form
afterwards and `gitlab-ctl reconfigure`.

---

## Restricted-network VMs (the common UBS shape)

When the VM has internal RPM repos but no direct route to `packages.gitlab.com`,
`yum.neo4j.com`, or `pypi.org`, the scripts honour two environment variables
that swap external sources for offline / mirrored ones.

### `PIP_INDEX_URL` — internal PyPI mirror

If your platform team has an Artifactory PyPI proxy (most do), pass its URL
and Python deps install from there instead of `pypi.org`:

```bash
PIP_INDEX_URL=https://artifactory.ubs.internal/api/pypi/pypi/simple/ \
PIP_TRUSTED_HOST=artifactory.ubs.internal \
PAT_TOKEN=<pat> VM_HOST=<vm> \
  ./install-sherlock.sh
```

### `OFFLINE_RPM_DIR` — pre-downloaded gitlab-ce / neo4j RPMs

When `packages.gitlab.com` and `yum.neo4j.com` are unreachable, download the
two RPMs on a workstation that has internet, SCP them to the VM, then point
the scripts at the directory:

```bash
# On a workstation with internet:
mkdir sherlock-rpms && cd sherlock-rpms
curl -L -O https://packages.gitlab.com/gitlab/gitlab-ce/packages/el/8/gitlab-ce-17.5.2-ce.0.el8.x86_64.rpm/download.rpm
mv download.rpm gitlab-ce-17.5.2-ce.0.el8.x86_64.rpm
curl -L -O https://dist.neo4j.org/rpm/community/neo4j-5.24.0-1.noarch.rpm
curl -L -O https://dist.neo4j.org/cypher-shell/cypher-shell-5.24.0-1.noarch.rpm
scp *.rpm root@<vm>:/root/sherlock-rpms/

# On the VM:
OFFLINE_RPM_DIR=/root/sherlock-rpms VM_HOST=<vm> ./install-gitlab.sh
OFFLINE_RPM_DIR=/root/sherlock-rpms PAT_TOKEN=<pat> VM_HOST=<vm> ./install-sherlock.sh
```

### Combined — typical UBS-shape POC

```bash
OFFLINE_RPM_DIR=/root/sherlock-rpms \
PIP_INDEX_URL=https://artifactory.ubs.internal/api/pypi/pypi/simple/ \
PIP_TRUSTED_HOST=artifactory.ubs.internal \
SHERLOCK_HOME=/app/C10/Sherlock \
VM_HOST=<vm-fqdn> \
  ./install-gitlab.sh

# create PAT in GitLab UI, then re-export everything plus PAT_TOKEN

OFFLINE_RPM_DIR=/root/sherlock-rpms \
PIP_INDEX_URL=https://artifactory.ubs.internal/api/pypi/pypi/simple/ \
PIP_TRUSTED_HOST=artifactory.ubs.internal \
SHERLOCK_HOME=/app/C10/Sherlock \
VM_HOST=<vm-fqdn> PAT_TOKEN=<pat> \
  ./install-sherlock.sh

SHERLOCK_HOME=/app/C10/Sherlock VM_HOST=<vm-fqdn> PAT_TOKEN=<pat> ./bootstrap.sh
```

## Fully airgapped VMs (no internet at all, even for OS packages)

Same as above plus mirror the OS packages too:

1. On a workstation with internet:
   - `dnf download --resolve --destdir=./rpms python3.12 git jq`
   - `pip download -r services/sherlock/requirements.txt -d ./wheels`
2. SCP `./rpms`, `./wheels`, the source zip to the VM.
3. On the VM: `dnf install ./rpms/*.rpm` first (handles the missing OS deps),
   then run install scripts with `PIP_INDEX_URL=` pointing at a `file://` of
   `./wheels` (or pass `--find-links` via a temporary `pip.conf`).

---

## Sidebar — try Podman first

Many shops that ban Docker permit **Podman** (rootless, daemon-less, ships with
RHEL). If `podman` and `podman-compose` are available, you can skip this entire
bundle and run `podman-compose up` against the unchanged repo-root
[docker-compose.yml](../../docker-compose.yml) — same outcome, one-tenth the work.
Worth a single ticket to your platform team before going fully native.
