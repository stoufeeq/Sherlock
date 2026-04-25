"""Autodoc workflow — clone the repo, update the Sherlock-managed README block,
push to a `sherlock/autodoc-*` branch, open (or refresh) an MR labeled
`sherlock::autodoc`.

Never commits to the default branch. Never touches files other than README.md.
The owning team reviews the draft MR in GitLab and merges if they agree.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.autodoc.generator import (
    SECTION_END,
    SECTION_START,
    AutodocFacts,
    gather_facts,
    merge_into_readme,
    render_section,
)
from app.cmdb_client import CMDBClient
from app.config import settings
from app.gitlab_client import GitLabClient
from app.graph.client import GraphClient
from app.llm.base import LLMProvider

log = logging.getLogger("sherlock.autodoc")

AUTODOC_MR_MARKER = "<!-- sherlock-autodoc-mr -->"


@dataclass
class AutodocOutcome:
    app_name: str
    action: str  # "created" | "updated" | "no_change" | "no_changes_needed" | "error"
    branch: str | None = None
    mr_iid: int | None = None
    mr_url: str | None = None
    message: str = ""


def _timestamp_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _run_git(args: list[str], *, cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), check=check,
        capture_output=True, text=True,
    )


def _existing_autodoc_mr(gitlab: GitLabClient, project_id: int) -> dict | None:
    for mr in gitlab.list_open_mrs(project_id, labels=settings.autodoc_mr_label):
        if AUTODOC_MR_MARKER in (mr.get("description") or ""):
            return mr
    return None


def _mr_description(app_name: str, facts: AutodocFacts) -> str:
    return (
        f"{AUTODOC_MR_MARKER}\n"
        f"## 🔎 Sherlock auto-documentation\n\n"
        f"Sherlock refreshed the auto-managed section of `README.md` for `{app_name}`.\n\n"
        f"**Why this MR exists** — the repo's README was either missing the "
        f"`sherlock:autodoc` section, or its content no longer matches what Sherlock "
        f"observed in the graph.\n\n"
        f"**What's inside**\n"
        f"- Ownership metadata (team, tier, on-call, runtime)\n"
        f"- Contracts this app provides: "
        f"{len(facts.exposes_endpoints)} REST endpoints, "
        f"{len(facts.publishes_topics)} topics, "
        f"{len(facts.written_tables)} tables, "
        f"{len(facts.written_files)} shared files\n"
        f"- Contracts this app consumes: "
        f"{len(facts.calls_endpoints)} REST calls, "
        f"{len(facts.consumed_topics)} topics, "
        f"{len(facts.read_tables)} tables, "
        f"{len(facts.read_files)} shared files\n"
        f"- Cross-app impact summary: affects {len(facts.downstream_apps)}, "
        f"depends on {len(facts.upstream_apps)}\n\n"
        f"**What to do** — review the README changes, merge if accurate, or edit "
        f"content OUTSIDE the `{SECTION_START}` / `{SECTION_END}` markers to preserve "
        f"team-authored narrative across regenerations.\n\n"
        f"---\n"
        f"_Opened by Sherlock. Regenerates on demand (`POST /api/autodoc/trigger/{app_name}`)._"
    )


def run_autodoc_for_app(
    *,
    app_name: str,
    project: dict,
    graph: GraphClient,
    cmdb: CMDBClient,
    gitlab: GitLabClient,
    llm: LLMProvider,
) -> AutodocOutcome:
    """Full pipeline: facts → rendered section → MR creation (or update)."""
    try:
        facts = gather_facts(graph.driver, cmdb, app_name)
    except KeyError as exc:
        return AutodocOutcome(app_name=app_name, action="error", message=str(exc))

    new_section = render_section(facts, llm)

    project_id = project["id"]
    default_branch = project.get("default_branch") or "main"
    clone_url = gitlab.clone_url(project["path_with_namespace"])

    tmp = Path(tempfile.mkdtemp(prefix=f"sherlock-autodoc-{app_name}-"))
    try:
        # 1. Shallow clone default branch
        try:
            _run_git(
                ["clone", "--depth", "1", "--branch", default_branch, clone_url, str(tmp / "repo")],
                cwd=Path("."),
            )
        except subprocess.CalledProcessError as exc:
            log.exception("git clone failed for %s", app_name)
            return AutodocOutcome(app_name=app_name, action="error",
                                  message=f"clone failed: {exc.stderr.strip()[:240]}")
        repo = tmp / "repo"

        _run_git(["config", "user.name", settings.autodoc_bot_name], cwd=repo)
        _run_git(["config", "user.email", settings.autodoc_bot_email], cwd=repo)

        # 2. Merge Sherlock section into README.md
        readme = repo / "README.md"
        existing = readme.read_text(errors="ignore") if readme.exists() else None
        updated = merge_into_readme(existing, new_section)

        # 3. Is this actually a change? (ignore markers-only whitespace churn)
        if existing is not None and existing.strip() == updated.strip():
            log.info("autodoc: no content change for %s", app_name)
            return AutodocOutcome(app_name=app_name, action="no_change",
                                  message="README already matches generated content")

        # 4. Reuse an open autodoc MR's branch if one exists (upsert)
        existing_mr = _existing_autodoc_mr(gitlab, project_id)
        if existing_mr:
            branch = existing_mr["source_branch"]
            try:
                _run_git(["fetch", "origin", branch], cwd=repo)
                _run_git(["checkout", "-B", branch, f"origin/{branch}"], cwd=repo)
                # rebase onto default to pick up any merged changes
                _run_git(["rebase", default_branch], cwd=repo, check=False)
                # re-apply our new README on top
                readme.write_text(updated)
            except subprocess.CalledProcessError:
                # branch may have gone stale — fall back to a fresh branch
                existing_mr = None

        if not existing_mr:
            branch = f"{settings.autodoc_branch_prefix}-{_timestamp_slug()}"
            _run_git(["checkout", "-b", branch], cwd=repo)
            readme.write_text(updated)

        # 5. Commit + push
        _run_git(["add", "README.md"], cwd=repo)
        status = _run_git(["status", "--porcelain"], cwd=repo)
        if not status.stdout.strip():
            return AutodocOutcome(app_name=app_name, action="no_change",
                                  branch=branch, message="generated content matches current head")

        _run_git(["commit", "-m", f"docs: refresh Sherlock auto-documentation section"], cwd=repo)
        _run_git(["push", "--set-upstream", "origin", branch], cwd=repo)

        # 6. Ensure label + open/update MR
        gitlab.ensure_label(project_id, settings.autodoc_mr_label, "#4F46E5",
                            description="Managed by Sherlock — auto-documentation refresh")
        description = _mr_description(app_name, facts)
        title = f"docs: refresh Sherlock auto-documentation for {app_name}"

        if existing_mr:
            gitlab.update_mr(project_id, existing_mr["iid"], title=title, description=description)
            return AutodocOutcome(
                app_name=app_name, action="updated",
                branch=branch, mr_iid=existing_mr["iid"], mr_url=existing_mr.get("web_url"),
                message="refreshed existing autodoc MR",
            )
        else:
            mr = gitlab.create_merge_request(
                project_id,
                source_branch=branch,
                target_branch=default_branch,
                title=title,
                description=description,
                labels=[settings.autodoc_mr_label],
            )
            return AutodocOutcome(
                app_name=app_name, action="created",
                branch=branch, mr_iid=mr["iid"], mr_url=mr.get("web_url"),
                message="opened new autodoc MR",
            )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
