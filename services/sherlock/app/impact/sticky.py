"""Sticky impact tags — the 'tag persists until fixed' part of the spec.

On break: open (or update) a GitLab issue in each affected repo with label
`impact::pending`, containing a stable marker so re-runs don't duplicate.

On fix (source app's default branch moves): re-scan, find resolved breaks, and
close the matching pending issues with label `impact::fixed`.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from app.gitlab_client import GitLabClient
from app.impact.diff import BreakingChange
from app.impact.engine import ResolvedImpact

LABEL_PENDING = "impact::pending"
LABEL_FIXED = "impact::fixed"
LABEL_COLORS = {
    LABEL_PENDING: "#F97316",  # orange
    LABEL_FIXED: "#10B981",    # green
}


def break_id(change: BreakingChange) -> str:
    """Stable short id for a break — used in issue markers."""
    key = f"{change.target_app}|{change.kind}|{change.detail}"
    return hashlib.sha256(key.encode()).hexdigest()[:10]


def issue_marker(*, source_app: str, source_mr_iid: int | None, change: BreakingChange) -> str:
    mr = source_mr_iid if source_mr_iid is not None else "main"
    return f"<!-- sherlock-impact:{source_app}!{mr}:{break_id(change)} -->"


def issue_title(source_app: str, change: BreakingChange) -> str:
    kind_short = {
        "endpoint_removed":             "Upstream removed endpoint",
        "endpoint_schema_changed":      "Upstream endpoint required-fields contract changed",
        "endpoint_schema_extended":     "Upstream endpoint extended (additive)",
        "deprecated_endpoint_removed":  "Upstream removed already-deprecated endpoint",
        "topic_publish_removed":        "Upstream stopped publishing topic",
        "topic_payload_changed":        "Upstream topic payload required-fields changed",
        "topic_payload_extended":       "Upstream topic payload extended (additive)",
        "table_write_removed":          "Upstream stopped writing table",
        "schema_unowned":               "Upstream schema ownership released",
        "lib_published_removed":        "Upstream library retired",
        "file_write_removed":           "Upstream stopped writing shared file feed",
    }.get(change.kind, change.kind)
    return f"[impact] {kind_short}: {change.detail}  (from {source_app})"


def issue_description(
    *,
    source_app: str,
    source_mr_iid: int | None,
    source_mr_url: str | None,
    source_commit: str | None,
    change: BreakingChange,
    marker: str,
) -> str:
    lines = [marker]
    lines.append(f"## Impact from `{source_app}`")
    lines.append("")
    mr_line = ""
    if source_mr_iid and source_mr_url:
        mr_line = f"MR: [{source_app}!{source_mr_iid}]({source_mr_url})"
    elif source_mr_url:
        mr_line = f"MR: {source_mr_url}"
    if mr_line:
        lines.append(mr_line)
    if source_commit:
        lines.append(f"Commit: `{source_commit[:12]}`")
    lines.append("")
    lines.append(f"**Break kind:** `{change.kind}`")
    lines.append(f"**Detail:** `{change.detail}`")
    lines.append("")
    lines.append("This issue was opened automatically by Sherlock because this app consumes "
                 f"something that `{source_app}` is changing.")
    lines.append("")
    lines.append("It will be labeled `impact::fixed` and closed automatically once the underlying "
                 "break is no longer present on the source app's default branch.")
    return "\n".join(lines)


@dataclass
class IssueOutcome:
    app: str
    action: str  # "created" | "updated" | "skipped"
    issue_iid: int | None = None
    issue_url: str | None = None


def apply_sticky_tags(
    *,
    gitlab: GitLabClient,
    source_app: str,
    source_mr_iid: int | None,
    source_mr_url: str | None,
    source_commit: str | None,
    impacts: list[ResolvedImpact],
    project_lookup: dict[str, dict],  # app_name -> gitlab project dict
) -> list[IssueOutcome]:
    outcomes: list[IssueOutcome] = []
    for resolved in impacts:
        change = resolved.change
        for app in resolved.impacted:
            proj = project_lookup.get(app.name)
            if not proj:
                continue
            project_id = proj["id"]

            # Make sure both labels exist
            for lbl_name, color in LABEL_COLORS.items():
                gitlab.ensure_label(project_id, lbl_name, color,
                                    description="Managed by Sherlock — cross-app impact tag")

            marker = issue_marker(source_app=source_app, source_mr_iid=source_mr_iid, change=change)
            existing = gitlab.find_issue_by_marker(project_id, marker)
            body = issue_description(
                source_app=source_app,
                source_mr_iid=source_mr_iid,
                source_mr_url=source_mr_url,
                source_commit=source_commit,
                change=change,
                marker=marker,
            )
            if existing:
                # refresh description; ensure label set to pending (reopen if previously closed)
                labels = {lbl for lbl in existing.get("labels", [])}
                labels.discard(LABEL_FIXED)
                labels.add(LABEL_PENDING)
                gitlab.update_issue(
                    project_id, existing["iid"],
                    labels=sorted(labels),
                    state_event="reopen" if existing.get("state") == "closed" else None,
                    description=body,
                )
                outcomes.append(IssueOutcome(app=app.name, action="updated",
                                             issue_iid=existing["iid"],
                                             issue_url=existing.get("web_url")))
            else:
                new_issue = gitlab.create_issue(
                    project_id,
                    title=issue_title(source_app, change),
                    description=body,
                    labels=[LABEL_PENDING],
                )
                outcomes.append(IssueOutcome(app=app.name, action="created",
                                             issue_iid=new_issue["iid"],
                                             issue_url=new_issue.get("web_url")))
    return outcomes


def clear_fixed_tags(
    *,
    gitlab: GitLabClient,
    source_app: str,
    surviving_markers: set[str],
    project_lookup: dict[str, dict],
) -> list[IssueOutcome]:
    """After rescanning source_app's default branch, close any pending impact issue
    whose marker is NOT in `surviving_markers` (meaning the underlying break is gone)."""
    outcomes: list[IssueOutcome] = []
    marker_prefix = f"<!-- sherlock-impact:{source_app}!"
    for app_name, proj in project_lookup.items():
        if app_name == source_app:
            continue
        project_id = proj["id"]
        for issue in gitlab.list_issues(project_id, labels=LABEL_PENDING, state="opened"):
            desc = issue.get("description") or ""
            if marker_prefix not in desc:
                continue
            # Find the marker token inside the description
            token = None
            for line in desc.splitlines():
                if line.startswith(marker_prefix):
                    token = line.strip()
                    break
            if not token:
                continue
            if token in surviving_markers:
                continue  # break still present on main
            labels = [lbl for lbl in issue.get("labels", []) if lbl != LABEL_PENDING]
            if LABEL_FIXED not in labels:
                labels.append(LABEL_FIXED)
            gitlab.update_issue(project_id, issue["iid"], labels=labels, state_event="close")
            gitlab.add_issue_note(project_id, issue["iid"],
                                  f"✅ Sherlock: underlying break resolved on `{source_app}` default branch.")
            outcomes.append(IssueOutcome(app=app_name, action="closed",
                                         issue_iid=issue["iid"],
                                         issue_url=issue.get("web_url")))
    return outcomes
