import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import asdict

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.analyzer.orchestrator import scan_repo
from app.cmdb_client import CMDBClient
from app.config import settings
from app.gitlab_client import GitLabClient
from app.graph import queries as gqueries
from app.graph.client import GraphClient
from app.graph_api import router as graph_api_router
from app.impact.diff import compute_breaks
from app.impact.engine import resolve as resolve_impact
from app.impact.report import COMMENT_MARKER, render_comment
from app.impact.sticky import apply_sticky_tags
from app.llm.factory import get_llm
from app.reconciler import ReconcilerState, run_reconciler_loop
from app.scan_service import project_lookup, scan_project

logging.basicConfig(level=settings.log_level)
log = logging.getLogger("sherlock")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.graph = GraphClient()
    app.state.graph.ensure_schema()
    app.state.gitlab = GitLabClient()
    app.state.cmdb = CMDBClient()
    app.state.reconciler = ReconcilerState()
    app.state.llm = get_llm()

    log.info("Sherlock ready (GitLab=%s, Neo4j=%s, groups=%s, llm=%s/%s)",
             settings.gitlab_internal_url, settings.neo4j_uri, settings.groups_list,
             app.state.llm.provider if hasattr(app.state.llm, "provider") else app.state.llm.name,
             getattr(app.state.llm, "model", "?"))

    app.state.reconciler_task = None
    if settings.reconcile_enabled:
        app.state.reconciler_task = asyncio.create_task(
            run_reconciler_loop(
                gitlab=app.state.gitlab,
                graph=app.state.graph,
                cmdb=app.state.cmdb,
                state=app.state.reconciler,
            )
        )
        log.info("reconciler started (interval=%ss)", settings.reconcile_interval_seconds)
    else:
        log.info("reconciler disabled (SHERLOCK_RECONCILE_ENABLED=false)")

    yield

    if app.state.reconciler_task:
        app.state.reconciler_task.cancel()
        try:
            await app.state.reconciler_task
        except asyncio.CancelledError:
            pass
    app.state.graph.close()


app = FastAPI(title="Sherlock", version="0.5.0", lifespan=lifespan)
app.include_router(graph_api_router)
app.mount("/ui", StaticFiles(directory="app/static", html=True), name="ui")


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/ui/")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": "0.5.0"}


# ---------- Scan ---------------------------------------------------------------


def _find_project(gitlab: GitLabClient, app_name: str) -> dict | None:
    return project_lookup(gitlab).get(app_name)


@app.post("/scan/{app_name}")
def scan_one(app_name: str) -> dict:
    gitlab: GitLabClient = app.state.gitlab
    project = _find_project(gitlab, app_name)
    if project is None:
        raise HTTPException(
            status_code=404,
            detail=f"project '{app_name}' not in groups {settings.groups_list}",
        )
    return scan_project(app_name, project, app.state.graph, app.state.cmdb, gitlab)


@app.post("/scan-all")
def scan_all() -> dict:
    gitlab: GitLabClient = app.state.gitlab
    summary = []
    for name, p in project_lookup(gitlab).items():
        try:
            summary.append(scan_project(name, p, app.state.graph, app.state.cmdb, gitlab))
        except Exception as exc:
            log.exception("scan failed for %s", name)
            summary.append({"app": name, "error": str(exc)})
    return {"scanned": len(summary), "results": summary}


# ---------- MR impact ----------------------------------------------------------


class AnalyzeMRRequest(BaseModel):
    app_name: str
    mr_iid: int
    source_branch: str
    target_branch: str = "main"
    post_comment: bool = True


def _analyze_mr(
    *,
    app_name: str,
    mr_iid: int,
    source_branch: str,
    target_branch: str,
    post_comment: bool,
    gitlab: GitLabClient,
    graph: GraphClient,
    cmdb: CMDBClient,
) -> dict:
    lookup = project_lookup(gitlab)
    project = lookup.get(app_name)
    if project is None:
        raise HTTPException(status_code=404, detail=f"project '{app_name}' not in any configured group")

    clone_url = gitlab.clone_url(project["path_with_namespace"])
    new_result = scan_repo(app_name=app_name, clone_url=clone_url, ref=source_branch)

    old_result = gqueries.load_current(graph.driver, app_name)
    breaks = compute_breaks(old_result, new_result)
    impacts = resolve_impact(breaks, driver=graph.driver, cmdb=cmdb)

    # Look up the source app's platform from CMDB for cross-boundary call-outs.
    source_svc = cmdb.get(app_name) or {}
    source_platform = source_svc.get("platform")

    body = render_comment(
        source_app=app_name,
        source_commit=new_result.commit_sha,
        target_branch=target_branch,
        impacts=impacts,
        source_platform=source_platform,
    )

    posted = None
    if post_comment:
        posted = gitlab.upsert_mr_note(project["id"], mr_iid, body, COMMENT_MARKER)

    source_mr_url = f"{project.get('web_url')}/-/merge_requests/{mr_iid}" if project.get("web_url") else None
    sticky_outcomes = apply_sticky_tags(
        gitlab=gitlab,
        source_app=app_name,
        source_mr_iid=mr_iid,
        source_mr_url=source_mr_url,
        source_commit=new_result.commit_sha,
        impacts=impacts,
        project_lookup=lookup,
        source_platform=source_platform,
    )

    return {
        "app": app_name,
        "mr_iid": mr_iid,
        "source_commit": new_result.commit_sha,
        "target_branch": target_branch,
        "breaks": [_break_summary(r) for r in impacts],
        "comment_posted": bool(posted),
        "note_id": (posted or {}).get("id"),
        "sticky_issues": [asdict(o) for o in sticky_outcomes],
    }


def _break_summary(r) -> dict:
    d = asdict(r.change)
    d["impacted"] = [asdict(a) for a in r.impacted]
    return d


@app.post("/analyze-mr")
def analyze_mr(req: AnalyzeMRRequest) -> dict:
    return _analyze_mr(
        app_name=req.app_name,
        mr_iid=req.mr_iid,
        source_branch=req.source_branch,
        target_branch=req.target_branch,
        post_comment=req.post_comment,
        gitlab=app.state.gitlab,
        graph=app.state.graph,
        cmdb=app.state.cmdb,
    )


# ---------- GitLab webhook -----------------------------------------------------


@app.post("/webhooks/gitlab")
async def webhook(
    request: Request,
    x_gitlab_token: str | None = Header(default=None),
    x_gitlab_event: str | None = Header(default=None),
) -> dict:
    if x_gitlab_token != settings.webhook_secret:
        raise HTTPException(status_code=401, detail="bad webhook token")
    payload = await request.json()

    if x_gitlab_event == "Push Hook":
        project = payload.get("project") or {}
        app_name = (project.get("path_with_namespace") or "").rsplit("/", 1)[-1]
        if not app_name:
            raise HTTPException(status_code=400, detail="missing project.path_with_namespace")
        default = project.get("default_branch") or "main"
        ref = (payload.get("ref") or "").removeprefix("refs/heads/")
        if ref and ref != default:
            return {"ignored_push": ref, "reason": "not default branch"}
        full = _find_project(app.state.gitlab, app_name)
        if not full:
            raise HTTPException(status_code=404, detail=f"project '{app_name}' not in any configured group")
        return scan_project(app_name, full, app.state.graph, app.state.cmdb, app.state.gitlab)

    if x_gitlab_event == "Merge Request Hook":
        attrs = payload.get("object_attributes") or {}
        action = attrs.get("action")
        if action not in {"open", "reopen", "update"}:
            return {"ignored_mr_action": action}
        project = payload.get("project") or {}
        app_name = (project.get("path_with_namespace") or "").rsplit("/", 1)[-1]
        if not app_name:
            raise HTTPException(status_code=400, detail="missing project.path_with_namespace")
        return _analyze_mr(
            app_name=app_name,
            mr_iid=attrs["iid"],
            source_branch=attrs["source_branch"],
            target_branch=attrs.get("target_branch") or "main",
            post_comment=True,
            gitlab=app.state.gitlab,
            graph=app.state.graph,
            cmdb=app.state.cmdb,
        )

    return {"ignored_event": x_gitlab_event}
