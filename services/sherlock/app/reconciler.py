"""Periodic reconciliation — keeps Sherlock's view of the enterprise in sync.

Per run (all idempotent):
  1. Enable `allow_local_requests` in GitLab application settings (no-op after first run).
  2. List every project in every configured group.
  3. Detect renames — a project whose numeric id matches a known Application but
     whose path differs → mark the old Application archived (renamed_to=<new>),
     fall through to treat the new path as a fresh discovery.
  4. For each project (in parallel, bounded):
       - Ensure Sherlock's webhook is installed.
       - If new → clone + scan into the graph.
       - If known → refresh CMDB metadata (team / tier / runtime / repo_url).
  5. Archival pass — any Application in the graph whose name wasn't seen this
     run (and isn't already archived) gets marked archived. Edges preserved.
"""

import asyncio
import logging
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.cmdb_client import CMDBClient
from app.config import settings
from app.gitlab_client import GitLabClient
from app.graph.client import GraphClient
from app.scan_service import scan_project

log = logging.getLogger("sherlock.reconciler")


@dataclass
class ReconcileRun:
    started_at: str
    completed_at: str
    duration_seconds: float
    groups: list[str]
    projects_seen: int
    new_projects: list[str] = field(default_factory=list)
    new_webhooks: list[str] = field(default_factory=list)
    refreshed: list[str] = field(default_factory=list)
    renamed: list[dict] = field(default_factory=list)        # [{old, new, project_id}]
    archived: list[str] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)


@dataclass
class ReconcilerState:
    """Shared between the background task and the /api/reconciler/* endpoints."""
    last_run: ReconcileRun | None = None
    last_runs: deque = field(default_factory=lambda: deque(maxlen=20))
    running_now: bool = False


def _ensure_webhook(gitlab: GitLabClient, project: dict) -> bool:
    """Register Sherlock's webhook on this project if not already present.
    Returns True when a new webhook was installed."""
    for h in gitlab.list_project_hooks(project["id"]):
        if h.get("url") == settings.sherlock_webhook_url:
            return False
    gitlab.ensure_webhook(project["id"], settings.sherlock_webhook_url, settings.webhook_secret)
    return True


def _detect_rename(
    project: dict,
    known_by_pid: dict[int, str],
    known_by_name: dict[str, dict],
    graph: GraphClient,
) -> dict | None:
    """If this project's numeric id matches a known Application under a DIFFERENT
    name, mark the old name archived with renamed_to=<new> and return the rename record.
    """
    pid = project.get("id")
    new_name = project["path"]
    if pid is None:
        return None
    old_name = known_by_pid.get(pid)
    if old_name is None or old_name == new_name:
        return None
    log.warning("rename detected: %r → %r (project_id=%s)", old_name, new_name, pid)
    graph.mark_archived(old_name, renamed_to=new_name)
    # remove from the known-by-name map so the downstream archival pass doesn't double-count
    known_by_name.pop(old_name, None)
    return {"old": old_name, "new": new_name, "project_id": pid}


def reconcile_once_sync(
    gitlab: GitLabClient,
    graph: GraphClient,
    cmdb: CMDBClient,
) -> ReconcileRun:
    started = datetime.now(timezone.utc)
    groups = settings.groups_list
    projects: list[dict] = []
    errors: list[dict] = []
    new_projects: list[str] = []
    new_webhooks: list[str] = []
    refreshed: list[str] = []
    renamed: list[dict] = []
    archived: list[str] = []

    # 1. List projects across all configured groups
    for g in groups:
        try:
            for p in gitlab.list_group_projects(g):
                projects.append(p)
        except Exception as exc:
            errors.append({"group": g, "error": str(exc)})
            log.exception("list_group_projects failed for %s", g)

    # 2. Snapshot what's in the graph today
    known_apps = graph.list_applications()
    known_by_name = {a["name"]: a for a in known_apps}
    known_by_pid: dict[int, str] = {
        a["project_id"]: a["name"] for a in known_apps
        if a.get("project_id") is not None and not a["archived"]
    }
    seen_names: set[str] = set()

    # 3. Rename detection (synchronous — avoids races in the parallel scan below)
    for p in projects:
        rec = _detect_rename(p, known_by_pid, known_by_name, graph)
        if rec:
            renamed.append(rec)

    # 4. Webhook + discovery loop — parallelized for new scans
    to_scan: list[dict] = []
    for p in projects:
        app_name = p["path"]
        seen_names.add(app_name)
        try:
            if _ensure_webhook(gitlab, p):
                new_webhooks.append(app_name)
                log.info("installed webhook on %s", app_name)
        except Exception as exc:
            errors.append({"project": app_name, "stage": "webhook", "error": str(exc)})
            log.exception("webhook registration failed for %s", app_name)
            continue

        if app_name not in known_by_name:
            to_scan.append(p)
        else:
            # Known-and-active → refresh CMDB metadata cheaply (no git clone)
            try:
                svc = cmdb.get(app_name) or {}
                graph.upsert_application(
                    name=app_name,
                    repo_url=p["web_url"],
                    team=svc.get("team"),
                    tier=svc.get("tier"),
                    runtime=svc.get("runtime"),
                    project_id=p.get("id"),
                )
                refreshed.append(app_name)
            except Exception as exc:
                errors.append({"project": app_name, "stage": "refresh", "error": str(exc)})
                log.exception("metadata refresh failed for %s", app_name)

    # 5. Parallel full-scan for brand-new projects
    if to_scan:
        with ThreadPoolExecutor(max_workers=settings.reconcile_max_workers) as pool:
            futures = {
                pool.submit(scan_project, p["path"], p, graph, cmdb, gitlab, clear_sticky=False): p
                for p in to_scan
            }
            for fut in as_completed(futures):
                p = futures[fut]
                try:
                    fut.result()
                    new_projects.append(p["path"])
                    log.info("auto-discovered + scanned: %s", p["path"])
                except Exception as exc:
                    errors.append({"project": p["path"], "stage": "scan", "error": str(exc)})
                    log.exception("scan failed for %s", p["path"])

    # 6. Archival pass — anything in-graph not in seen_names (and not already archived)
    renamed_old = {r["old"] for r in renamed}
    for app in known_apps:
        name = app["name"]
        if app["archived"]:
            continue
        if name in renamed_old:
            # Step 3 already archived this node with renamed_to=<new>. Don't
            # overwrite the renamed_to — but still report it in the run summary.
            archived.append(name)
            continue
        if name in seen_names:
            continue
        try:
            graph.mark_archived(name)
            archived.append(name)
            log.warning("archived (no longer in any configured group): %s", name)
        except Exception as exc:
            errors.append({"project": name, "stage": "archive", "error": str(exc)})
            log.exception("archive failed for %s", name)

    completed = datetime.now(timezone.utc)
    return ReconcileRun(
        started_at=started.isoformat(),
        completed_at=completed.isoformat(),
        duration_seconds=round((completed - started).total_seconds(), 2),
        groups=groups,
        projects_seen=len(projects),
        new_projects=new_projects,
        new_webhooks=new_webhooks,
        refreshed=refreshed,
        renamed=renamed,
        archived=archived,
        errors=errors,
    )


async def run_reconciler_loop(
    gitlab: GitLabClient,
    graph: GraphClient,
    cmdb: CMDBClient,
    state: ReconcilerState,
) -> None:
    try:
        await asyncio.to_thread(gitlab.ensure_allow_local_requests)
    except Exception:
        log.exception("ensure_allow_local_requests failed (continuing)")

    while True:
        state.running_now = True
        try:
            run = await asyncio.to_thread(reconcile_once_sync, gitlab, graph, cmdb)
            state.last_run = run
            state.last_runs.append(run)
            log.info(
                "reconciled: groups=%s seen=%d new=%d hooks=%d refreshed=%d renamed=%d archived=%d errors=%d in %.2fs",
                run.groups, run.projects_seen, len(run.new_projects),
                len(run.new_webhooks), len(run.refreshed),
                len(run.renamed), len(run.archived), len(run.errors),
                run.duration_seconds,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("reconcile run failed")
        finally:
            state.running_now = False
        try:
            await asyncio.sleep(settings.reconcile_interval_seconds)
        except asyncio.CancelledError:
            raise
