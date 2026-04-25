# Sherlock

Enterprise framework that maps application interdependencies across GitLab, auto-generates documentation, and surfaces the blast radius of code changes.

## What's in this repo

```
.
├── docker-compose.yml         # GitLab CE + Postgres + Redpanda + CMDB stub
├── docker-compose.sherlock.yml (future) Sherlock services
├── services/                  # Sherlock's own services
│   └── sherlock-cmdb-stub/    # Dummy CMDB for local dev
├── fixtures/                  # 10 dummy banking apps pushed to local GitLab as test repos
│   ├── legacy-ledger/           (COBOL)
│   ├── shared-domain-lib/       (Java library)
│   ├── account-service/         (Java/Spring)
│   ├── transaction-service/     (Java/Spring)
│   ├── customer-service/        (Java/Spring)
│   ├── notification-service/    (Java/Spring)
│   ├── fraud-detection/         (Python/FastAPI)
│   ├── analytics-service/       (Python/FastAPI)
│   ├── web-portal-bff/          (Node/Express)
│   └── mobile-bff/              (Node/Express)
└── scripts/
    ├── bootstrap-gitlab.sh    # create GitLab projects + push seed repos
    └── gen-mr.sh              # scripted MR generator for chaos testing
```

## Quick start (Loop 1)

**1. Bring up the local infra**

```bash
cp .env.example .env
make up
```

This starts:
- **GitLab CE** at <http://gitlab.local:8080> (add `127.0.0.1 gitlab.local` to `/etc/hosts`)
- **Postgres** at `localhost:5432` (shared DB for fixture apps)
- **Redpanda** at `localhost:9092` (Kafka-compatible broker)
- **CMDB stub** at <http://localhost:8500>

First GitLab boot takes 3–5 minutes. Follow progress with `make logs-gitlab`.

**2. Set the initial GitLab root password**

```bash
make gitlab-root-password
```

**3. Create a Personal Access Token**

Sign in to <http://gitlab.local:8080> as `root`, go to **User Settings → Access Tokens**, create a token with `api`, `read_repository`, `write_repository` scopes. Put it in `.env` as `GITLAB_TOKEN=...`.

**4. Bootstrap the 10 fixture repos**

```bash
make bootstrap
```

Creates a `banking` group, 10 projects, and pushes each seed repo from `fixtures/` into GitLab.

**5. Verify**

```bash
make status
```

Lists the 10 projects and their clone URLs. Visit any in the browser to confirm.

## What Loop 1 gives you

- Self-hosted GitLab with 10 realistic banking repos
- A dummy CMDB listing the 10 services, their teams, tiers, and on-call channels
- Enough code + contracts in each repo for Sherlock's analyzers to extract a rich dependency graph

Loop 2 will add Sherlock's ingest + analyzer + Neo4j graph.
Loop 3 will add the MR impact bot.

## Resource requirements

- ~8 GB free RAM (GitLab alone is ~4 GB)
- ~20 GB free disk

## Teardown

```bash
make down        # stop containers
make clean       # stop + delete volumes (wipes GitLab state)
```
