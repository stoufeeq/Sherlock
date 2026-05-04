# Sherlock — Dependency Intelligence Platform

Enterprise-scale framework that ingests GitLab repos, builds a live cross-application
dependency graph, surfaces breaking-change blast radius at MR time, and auto-documents
each app's contracts. Targeted at UBS; pitched as a 3-month pilot.

This file is the orientation guide. For per-task durable knowledge see the user's auto-memory
under `~/.claude/projects/-Users-toufeeq-Projects-Sherlock/memory/`.

---

## Current state (live in the local POC)

Six work loops are complete and end-to-end demoable:

| Loop | What it added |
|---|---|
| **1** | Local infra (GitLab CE, Postgres, Redpanda, Neo4j, CMDB stub) + 10 polyglot fixture banking apps (Java/Spring, Python/FastAPI, Node/Express, COBOL) wired with REST/Kafka/SQL/file-feed contracts. |
| **2** | `sherlock` service: ingest webhooks, language-aware analyzers, Neo4j graph writer. Initial canvas. |
| **3** | MR impact bot — diffs branch graph against main, posts a structured MR note on breaking changes. |
| **4A** | Visualization canvas: Cytoscape.js, two modes (App view / Contract view), UBS light theme, dagre `BT` layout. |
| **4B** | Precise REST call paths via per-language regex extractors (Java/Python/JS); shape-hash detection of OpenAPI / AsyncAPI payload changes. |
| **4C** | Sticky impact tags — `impact::pending` issue auto-opened in each affected downstream repo, auto-closed (`impact::fixed`) when the source app's main rescan no longer reproduces the break. |
| **— file feeds** | Detects shared-volume reads/writes (Java/Python/JS/COBOL). New `FileFeed` node type and `READS_FILE`/`WRITES_FILE` edges. |
| **5A** | Periodic reconciler (`/api/reconciler/*`) — auto-discovers new GitLab projects, installs webhooks, refreshes CMDB metadata. Multi-group via `GITLAB_GROUPS`. |
| **5B** | Archival + rename detection via stable `project_id` tracking; parallel scan via `ThreadPoolExecutor`. |
| **6** | LLM-backed auto-documentation — pluggable provider (`mock` / `gemini` / `azure_openai`), per-app draft MR with a marker-delimited Sherlock section in `README.md`. UI button. |
| **— hybrid platform** | CMDB-driven `platform` field (azure / on-prem / library) merged into the graph. Cross-platform impacts surface a 🚨 banner in the MR comment, an `impact::cross-platform` label on sticky issues, and coloured rings (Azure blue / slate) on the canvas. |
| **— api gateway** | APIGEE-style gateway resolver: caller hits `https://api.ubs.com/banking/v1/...`, Sherlock loads `services/sherlock/config/gateway-routes.yaml`, rewrites to the real backend app + path, and stamps `via_gateway` on the CALLS edge so the canvas dashes it red. Mixed estate supported (some apps direct, some via gateway). Both BFFs in the fixture demonstrate the mix. |
| **— shift-left** | `POST /analyze-diff` runs the same engine as the MR bot but takes an in-flight `working_files` map + `deleted_files` list — no MR, no GitLab side-effects. Powers `scripts/sherlock-impact-check.sh`, which clones the diff vs `origin/main`, posts to the endpoint, and prints a coloured summary of breaks + cross-platform impacts. Install as a git pre-push hook with `make install-pre-push repo=<path>`. |
| **— vscode extension** | `tools/vscode-sherlock/` — single-file JS extension (no build step). Status-bar count + `Sherlock: Analyze Impact of Pending Changes` command + webview report. Same `/analyze-diff` payload as the pre-push hook. Builds to a `.vsix` via `make extension-package` and installs in **VS Code / Cursor / Windsurf / Antigravity** (all VS Code forks, same extension API). |
| **— multi-hop impact** | `/api/impact/{app}?depth=N` walks the cross-app coupling graph N hops via Python BFS over per-hop Cypher templates (cap 10). Response carries a `by_hop` breakdown so the canvas colours each hop a different shade (UBS-red → orange → amber → yellow → slate). Hop slider + per-hop legend on the side panel; surfaces 2nd/3rd-order blast radius for "what about the apps that depend on the apps I depend on?" |

A CTO pitch deck is generated from `tools/deck/generate.py` into
[Sherlock_CTO_Pitch.pptx](Sherlock_CTO_Pitch.pptx) (28 slides, UBS-themed).

---

## Repo layout

```
Sherlock/
├── docker-compose.yml          # GitLab + Postgres + Redpanda + CMDB + Neo4j + Sherlock
├── Makefile                    # all routine commands: up/down/scan/webhooks/demos
├── .env / .env.example         # service config; LLM keys; reconciler interval
├── README.md                   # quick-start for the local stack
├── Sherlock_CTO_Pitch.pptx     # generated deck (do not edit by hand)
│
├── services/
│   ├── sherlock/               # the platform itself (FastAPI + analyzers)
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── app/
│   │       ├── main.py         # FastAPI app + lifespan + webhook handler
│   │       ├── config.py       # pydantic-settings; LLM/reconcile config
│   │       ├── gitlab_client.py
│   │       ├── cmdb_client.py
│   │       ├── scan_service.py # shared scan flow used by HTTP + reconciler
│   │       ├── reconciler.py   # 60s loop: discover/install-hooks/scan/archive/rename
│   │       ├── graph/
│   │       │   ├── client.py   # Neo4j driver; node/edge upserts; constraints
│   │       │   └── queries.py  # read-only queries for impact engine
│   │       ├── graph_api.py    # /api/graph, /api/app-graph, /api/impact, /api/reconciler/*, /api/autodoc/*
│   │       ├── analyzer/
│   │       │   ├── orchestrator.py   # clone → walk → dispatch
│   │       │   ├── manifests.py      # pom.xml, requirements.txt, pyproject, package.json
│   │       │   ├── openapi.py        # exposed REST + payload shape hash
│   │       │   ├── asyncapi.py       # publish/subscribe topics + payload hash
│   │       │   ├── sql.py            # DDL + DML heuristics; schema ownership
│   │       │   ├── code_refs.py      # outbound HTTP host + (method, path) per language
│   │       │   ├── api_gateway.py    # APIGEE-style resolver: rewrites gateway URLs to backend apps; stamps via_gateway on CALLS edges
│   │       │   └── files.py          # shared-volume file I/O incl. COBOL SELECT/ASSIGN
│   │       ├── impact/
│   │       │   ├── diff.py     # AnalysisResult diff → BreakingChange list
│   │       │   ├── engine.py   # walk graph for affected apps; CMDB enrichment
│   │       │   ├── predictive.py    # /analyze-diff: shift-left impact (working-tree overlay → diff → impacts JSON, no MR side-effects)
│   │       │   ├── report.py   # markdown rendering for MR comment
│   │       │   └── sticky.py   # impact::pending issue lifecycle
│   │       ├── llm/
│   │       │   ├── base.py     # LLMProvider Protocol + LLMResponse
│   │       │   ├── mock.py     # zero-key fallback
│   │       │   ├── gemini.py   # google-generativeai (lazy import)
│   │       │   ├── azure_openai.py   # openai SDK (lazy import)
│   │       │   └── factory.py  # SHERLOCK_LLM_PROVIDER → instance
│   │       ├── autodoc/
│   │       │   ├── generator.py     # build Sherlock-managed README section
│   │       │   └── workflow.py      # clone → branch → commit → push → MR upsert
│   │       └── static/         # canvas UI (HTML + CSS + Cytoscape JS)
│   │
│   └── sherlock-cmdb-stub/     # FastAPI mock CMDB; YAML-backed
│
├── fixtures/                   # the 10 dummy banking apps pushed into local GitLab
│   ├── legacy-ledger/          (COBOL — reads POSTINGS.DAT, writes LEDGER.RPT)
│   ├── shared-domain-lib/      (Java library)
│   ├── account-service/        (Java/Spring)
│   ├── transaction-service/    (Java/Spring — also writes POSTINGS.DAT)
│   ├── customer-service/       (Java/Spring)
│   ├── notification-service/   (Java/Spring)
│   ├── analytics-service/      (Python/FastAPI — also reads LEDGER.RPT)
│   ├── fraud-detection/        (Python/FastAPI)
│   ├── web-portal-bff/         (Node/Express)
│   └── mobile-bff/             (Node/Express)
│
├── scripts/
│   ├── bootstrap-gitlab.sh        # create banking group + push 10 seed repos
│   ├── status.sh                  # list projects in banking group
│   ├── register-webhooks.sh       # bulk-install Sherlock webhooks (also done by reconciler)
│   ├── demo-breaking-change.sh    # opens a breaking MR on account-service
│   └── demo-break-file.sh         # opens a breaking MR on transaction-service (file-feed break)
│
├── tools/deck/
│   ├── generate.py             # python-pptx deck builder (UBS theme)
│   ├── requirements.txt
│   └── README.md               # slide map + presenter checklist
│
├── tools/vscode-sherlock/      # VS Code / Cursor / Windsurf / Antigravity extension (MVP)
│   ├── package.json            # extension manifest (commands, settings, activation events)
│   ├── extension.js            # single-file JS extension — status bar, command, webview
│   ├── README.md               # install + dev instructions
│   └── .vscodeignore
│
└── deploy/native-rhel/         # Native (Docker-free) RHEL VM install bundle
    ├── README.md               # step-by-step runbook
    ├── install-gitlab.sh       # GitLab CE Omnibus install + first reconfigure
    ├── install-sherlock.sh     # Neo4j + Sherlock + CMDB stub + systemd + firewall
    ├── bootstrap.sh            # push fixture repos to local GitLab + first scan
    ├── sherlock.env.example    # template for /etc/sherlock/sherlock.env
    └── systemd/
        ├── sherlock.service    # Type=exec, EnvironmentFile=/etc/sherlock/sherlock.env
        └── cmdb-stub.service
```

---

## Common commands (run from repo root)

```bash
make help                       # list every target
make up                         # bring up the whole stack
make down                       # stop containers (data preserved)
make clean                      # stop + wipe all volumes (destructive)
make logs-sherlock              # tail Sherlock logs
make gitlab-root-password       # print initial root password (only valid <24h)

make bootstrap                  # create 10 fixture repos in GitLab
make status                     # list fixture projects in GitLab
make webhooks                   # bulk-install webhooks (reconciler also does this)

make scan-all                   # rescan every repo into the graph
make scan app=legacy-ledger     # rescan one repo
make demo-break                 # open a breaking-change MR on account-service
make neo4j                      # print Neo4j browser URL + credentials
```

Sherlock-specific (rebuild after editing Python or static UI):

```bash
docker compose build sherlock && docker compose up -d --force-recreate sherlock
```

Regenerate the pitch deck:

```bash
cd tools/deck && .venv/bin/python generate.py
```

Native (Docker-free) install on a RHEL VM — for environments where Docker isn't
permitted and the corporate GitLab is RBAC-gated. Stands up local GitLab CE +
Neo4j + Sherlock + CMDB stub via systemd:

```bash
# from a clean RHEL 8/9 VM, after `git clone` to /opt/sherlock
cd /opt/sherlock/deploy/native-rhel
sudo VM_HOST=<vm-fqdn> ./install-gitlab.sh        # GitLab CE Omnibus
# create a PAT in the GitLab UI, then:
sudo PAT_TOKEN=<pat> VM_HOST=<vm-fqdn> ./install-sherlock.sh
sudo PAT_TOKEN=<pat> VM_HOST=<vm-fqdn> ./bootstrap.sh
```

Full runbook + verification + airgapped-VM notes in
[deploy/native-rhel/README.md](deploy/native-rhel/README.md).

---

## Service URLs (defaults)

| Service | URL | Notes |
|---|---|---|
| GitLab | http://localhost:8080 | root password from `make gitlab-root-password` |
| Sherlock UI | http://localhost:8001/ui/ | redirects from `/`; light UBS theme |
| Sherlock API | http://localhost:8001 | `/health`, `/api/...`, `/docs` (Swagger) |
| Neo4j Browser | http://localhost:7474 | `neo4j` / `sherlock-dev` |
| CMDB stub | http://localhost:8500 | `/services`, `/services/{id}` |
| Postgres | `localhost:5434` | **Not** 5432 — host conflict; in-container is 5432 |
| Redpanda | `localhost:9092` | Kafka-compatible |

---

## Detection coverage (what the analyzers extract)

| Coupling | Signal source | Languages |
|---|---|---|
| REST endpoints exposed | `openapi.yaml` paths + req/res schema hashes | (language-agnostic) |
| REST calls outbound | `.uri("/...")` (Java) · `.get("/...")` (Python httpx) · `http.get('/...')` (axios) | Java · Python · JS/TS |
| Path normalization | `{id}` / `${var}` / `{account_id}` → `{*}` so caller and exposer match | all |
| API gateway unravelling | `services/sherlock/config/gateway-routes.yaml` (APIGEE-bundle-shaped); resolver rewrites `host=api.ubs.com path=/banking/v1/...` to `target_app + backend_path`; CALLS edge stamped with `via_gateway=<name>` and rendered dashed-red on the canvas | (host-agnostic) |
| Events published / consumed | `asyncapi.yaml` channels + payload-hash for shape changes | (language-agnostic) |
| Database tables | `CREATE TABLE schema.table` + `FROM schema.table` heuristics + Flyway YAML schema ownership | SQL + Java/Python/COBOL |
| Shared file feeds | path string literals on `/shared/`, `/mnt/feeds/`, `/inbound/`, `/outbound/` + classification by nearby keywords; COBOL `SELECT/ASSIGN` + `OPEN INPUT/OUTPUT` parsed authoritatively | Java · Python · JS · **COBOL** |
| Library dependencies | `pom.xml` · `requirements.txt` · `pyproject.toml` · `package.json` | Java · Python · Node |

Graph schema: 7 node types (`Application`, `Endpoint`, `Topic`, `DBSchema`, `DBTable`, `FileFeed`, `Library`) and 12 edge types. Constraints in [services/sherlock/app/graph/client.py](services/sherlock/app/graph/client.py) ensure unique keys per type.

---

## Sherlock API surface

Read endpoints (no auth in dev):

- `GET /health` — readiness
- `GET /ui/` — canvas SPA
- `GET /docs` — FastAPI Swagger UI
- `GET /api/graph?include_archived=` — full Cytoscape JSON (apps + endpoints + topics + tables + files + libs)
- `GET /api/app-graph?include_archived=` — collapsed app-to-app edges only
- `GET /api/apps?include_archived=` — list apps with CMDB metadata + counts + archival flags
- `GET /api/impact/{app}?direction=downstream|upstream&depth=N` — multi-hop reachable apps; response includes `affected_apps` (flat) + `by_hop` (per-hop breakdown). Depth defaults to 1 (legacy MR-bot behaviour); cap is 10.
- `GET /api/reconciler/status` — last 20 reconciliation runs

Write endpoints:

- `POST /scan-all` · `POST /scan/{app}` — manual full or per-app rescan
- `POST /analyze-mr` — analyze an MR (body: `app_name`, `mr_iid`, `source_branch`, `post_comment`)
- `POST /analyze-diff` — shift-left: same engine, takes `working_files` + `deleted_files` in the request body, returns impacts JSON (no MR, no sticky issues)
- `POST /webhooks/gitlab` — Push + Merge Request hooks (token-authed)
- `POST /api/reconciler/trigger` — kick off an immediate reconcile pass
- `POST /api/autodoc/trigger/{app}` — generate / refresh autodoc MR for one app

---

## Three distinct outputs (don't conflate them — recurring source of confusion)

| Trigger | Where it lands | Reviewed by |
|---|---|---|
| Developer edits code locally | Pre-push hook prints impact summary in the terminal (no GitLab side-effect) | The developer themselves |
| Author opens a breaking-change MR | Comment on the **author's own MR** | Author's own team |
| Same event | `impact::pending` issue in **each downstream repo** (sticky tag) | Each affected team |
| Manual or scheduled autodoc trigger | Draft README MR in **the app's own repo** | App's own team |

Autodoc does **not** propagate to downstream repos. That's the sticky-tag flow. The pre-push hook is the same engine as the MR comment — just earlier in the loop.

---

## Conventions used throughout

- **`from __future__ import annotations` not used**; Python 3.12 in the container handles `X | None` natively.
- **Marker-based idempotency** for everything that mutates GitLab: MR notes look for `<!-- sherlock-impact-v1 -->`, MR descriptions look for `<!-- sherlock-autodoc-mr -->`, sticky issues look for `<!-- sherlock-impact:{src_app}!{mr}:{break_hash} -->`.
- **Lazy LLM SDK imports** — `app/llm/gemini.py` and `app/llm/azure_openai.py` import their respective vendor SDK only when instantiated, so the container boots even if a SDK is missing.
- **Static UI files (`app/static/*`) are baked into the Sherlock Docker image.** Editing CSS/JS/HTML requires a Sherlock rebuild before the change is served.
- **Sync code wrapped via `asyncio.to_thread`** when called from async handlers (reconciler loop, autodoc trigger).
- **Comments explain WHY, not WHAT** — the codebase keeps prose to a minimum and prefers self-explanatory names.

---

## Known gotchas (will bite if forgotten)

1. **Postgres host port is 5434**, not 5432 (a `morpheus-postgres` container occupies 5432). All fixture app DSNs reference `postgres:5432` (in-container) or `localhost:5434` (from host).
2. **GitLab Puma needs `puma['port'] = 8081`** in `GITLAB_OMNIBUS_CONFIG`; otherwise it collides with nginx and crash-loops on `EADDRINUSE`. Do not remove the line in [docker-compose.yml](docker-compose.yml).
3. **`gitlab_rails['initial_root_password']` must NOT be set from an empty env var.** GitLab rejects values shorter than 8 chars including `''`. Compose deliberately omits the line; password is auto-generated into `/etc/gitlab/initial_root_password` (`make gitlab-root-password` reads it).
4. **`/-/readiness` returns 404 to external IPs** by default (monitoring_whitelist). Use `/users/sign_in` or `/api/v4/version` (with token) for external probing. Container healthcheck works because it runs from inside.
5. **Pydantic env-var aliasing** — `SHERLOCK_LLM_PROVIDER` doesn't auto-map to field `llm_provider` because the prefix doesn't match. The field uses `validation_alias=AliasChoices("sherlock_llm_provider", "llm_provider")` so both names work.
6. **GitLab DELETE is a soft-rename** to `<name>-deletion_scheduled-<id>` with a multi-day grace period. Sherlock's reconciler sees this as a rename event; archival-by-disappearance only fires after the grace period actually purges the project.
7. **Gemini 2.5 Flash uses thinking tokens** that count against `max_output_tokens`. The autodoc generator passes `max_tokens=2048` for the Purpose call so the model has headroom. Bumping below ~512 risks empty / truncated responses with `finish_reason=MAX_TOKENS`.
8. **MR comment / sticky issue idempotency depends on the marker existing in the body.** If the body is edited by hand to remove the marker, Sherlock will create a duplicate on its next run.
9. **Edit tool requires Read first**. When iterating on a Python file across multiple sessions, re-Read before each batch of Edits or the operation rejects.

---

## What is NOT yet built (don't waste time looking)

- **Scheduled autodoc loop with priority scoring** (slide 13 H2 pilot work) — only manual `/api/autodoc/trigger/{app}` exists today.
- **Hierarchical doc summarization** (function → file → module → service) — autodoc currently produces a single per-app section.
- **APM (Dynatrace) integration** — Loop H4.
- **Backstage plugin / SLA dashboard** — Loop H3.
- **gRPC / GraphQL contract detection** — only OpenAPI + AsyncAPI today.
- **GitLab Group-level webhooks** — reconciler is the substitute (≤60s discovery latency).
- **CI component** that teams `include:` from `.gitlab-ci.yml` — webhooks-only today.
- **VS Code extension polish (Phase B)** — current MVP ships status-bar + command + webview. Roadmap: Problems-panel diagnostics, CodeLens on endpoint definitions, GitLab OIDC instead of PAT.
- **`impact::acknowledged` flow** for downstream teams to dismiss without closing.
- **Scheduled remote agents** for periodic doc regeneration of stale repos.

---

## Pitch deck

The deck is generated, not hand-edited. To change content, edit
[tools/deck/generate.py](tools/deck/generate.py) and re-run. See
[tools/deck/README.md](tools/deck/README.md) for the slide map, presenter
checklist, and the "three outputs" distinction (slides 8 / 10 / 11).
