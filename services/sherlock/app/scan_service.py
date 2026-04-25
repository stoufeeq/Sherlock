"""Core scan flow shared between the HTTP endpoints (main.py) and the reconciler."""

from dataclasses import asdict

from app.analyzer.orchestrator import scan_repo
from app.cmdb_client import CMDBClient
from app.gitlab_client import GitLabClient
from app.graph.client import GraphClient
from app.impact.sticky import clear_fixed_tags


def host_to_app_map(cmdb: CMDBClient) -> dict[str, str]:
    return {svc["id"]: svc["id"] for svc in cmdb.list_services()}


def project_lookup(gitlab: GitLabClient) -> dict[str, dict]:
    """path -> project dict, across every group Sherlock is configured to watch."""
    from app.config import settings
    out: dict[str, dict] = {}
    for g in settings.groups_list:
        try:
            for p in gitlab.list_group_projects(g):
                out[p["path"]] = p
        except Exception:
            # partial failure (one group down) shouldn't break the whole lookup
            continue
    return out


def scan_project(
    app_name: str,
    project: dict,
    graph: GraphClient,
    cmdb: CMDBClient,
    gitlab: GitLabClient,
    *,
    clear_sticky: bool = True,
) -> dict:
    """Clone `project` at its default branch, analyze, apply to the graph.

    When `clear_sticky=True`, also closes any `impact::pending` issues whose
    underlying break is no longer reproducible on this app's main — used when
    the scan originates from a push-to-default-branch event.
    """
    clone_url = gitlab.clone_url(project["path_with_namespace"])
    ref = project.get("default_branch") or "main"
    result = scan_repo(app_name=app_name, clone_url=clone_url, ref=ref)

    svc = cmdb.get(app_name) or {}
    graph.upsert_application(
        name=app_name,
        repo_url=project["web_url"],
        team=svc.get("team"),
        tier=svc.get("tier"),
        runtime=svc.get("runtime"),
        project_id=project.get("id"),
    )
    graph.apply_analysis(result, host_to_app_map(cmdb))

    closed: list = []
    if clear_sticky:
        closed = clear_fixed_tags(
            gitlab=gitlab,
            source_app=app_name,
            surviving_markers=set(),
            project_lookup=project_lookup(gitlab),
        )

    return {
        "app": app_name,
        "commit": result.commit_sha,
        "exposed": len(result.exposed_endpoints),
        "calls": len(result.called_endpoints),
        "published_topics": len(result.published_topics),
        "consumed_topics": len(result.consumed_topics),
        "deps": len(result.library_deps),
        "owned_schemas": result.owned_schemas,
        "read_tables": result.read_tables,
        "written_tables": result.written_tables,
        "read_files": result.read_files,
        "written_files": result.written_files,
        "sticky_issues_closed": [asdict(c) for c in closed],
    }
