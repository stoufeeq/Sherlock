"""Pre-commit / pre-push impact analysis.

Same engine as the MR-time bot, but takes an in-flight working-tree snapshot
instead of cloning a branch ref. Used by:
  - POST /analyze-diff      (HTTP API)
  - VS Code extension       (over the API)
  - git pre-push hook       (CLI shim over the API)

Fundamentally a thin wrapper around: clone base → overlay caller's files →
scan the overlaid tree → diff against the current graph → resolve impacts.

No GitLab side-effects (no MR comment, no sticky issues). The IDE / hook is
the user-facing surface; this module just returns JSON-shaped results.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Iterable

from app.analyzer.orchestrator import _clone, scan_directory
from app.cmdb_client import CMDBClient
from app.gitlab_client import GitLabClient
from app.graph import queries as gqueries
from app.impact.diff import compute_breaks
from app.impact.engine import resolve as resolve_impact
from neo4j import Driver

log = logging.getLogger(__name__)

# Files outside CODE_EXTS / manifests are uninteresting — reject anything obviously
# binary or out-of-scope before touching disk. Keeps overlays tight.
_OVERLAY_DENY_SUFFIXES = {
    ".class", ".jar", ".war", ".pyc", ".so", ".dll",
    ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".tar", ".gz",
}


def _validate_relpath(rel: str) -> Path:
    """Reject path-traversal attempts and absolute paths.

    Working-tree paths come straight from a developer's IDE; even a benign typo
    like a leading `/` would write outside the temp dir. Belt-and-braces here.
    """
    p = Path(rel)
    if p.is_absolute():
        raise ValueError(f"absolute path not allowed: {rel}")
    if any(part == ".." for part in p.parts):
        raise ValueError(f"path traversal not allowed: {rel}")
    return p


def _apply_overlay(
    root: Path,
    *,
    working_files: dict[str, str] | None,
    deleted_files: Iterable[str] | None,
) -> tuple[int, int]:
    """Write `working_files` into `root` and remove `deleted_files`.

    Returns (written, deleted) for logging.
    """
    written = 0
    deleted = 0
    for rel, content in (working_files or {}).items():
        rel_path = _validate_relpath(rel)
        if rel_path.suffix.lower() in _OVERLAY_DENY_SUFFIXES:
            continue
        target = root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        written += 1
    for rel in (deleted_files or []):
        rel_path = _validate_relpath(rel)
        target = root / rel_path
        if target.exists():
            target.unlink()
            deleted += 1
    return written, deleted


def analyze_diff(
    *,
    app_name: str,
    base_ref: str,
    working_files: dict[str, str] | None,
    deleted_files: list[str] | None,
    gitlab: GitLabClient,
    driver: Driver,
    cmdb: CMDBClient,
    project_lookup: dict[str, dict],
) -> dict:
    """Run the same impact analysis the MR bot runs, against an in-flight diff.

    `project_lookup` is the same map main.py already builds (path → project dict).
    Caller is responsible for having ensured `app_name` is in it.
    """
    project = project_lookup.get(app_name)
    if project is None:
        raise ValueError(f"project '{app_name}' not in any configured group")

    clone_url = gitlab.clone_url(project["path_with_namespace"])

    tmp = Path(tempfile.mkdtemp(prefix=f"sherlock-diff-{app_name}-"))
    try:
        _clone(clone_url, base_ref, tmp)
        written, deleted = _apply_overlay(
            tmp, working_files=working_files, deleted_files=deleted_files,
        )
        log.info("analyze-diff overlay for %s: %d written, %d deleted",
                 app_name, written, deleted)

        # Synthetic commit SHA — the result is never written to the graph; this
        # value just travels through to the response so callers can correlate.
        new_result = scan_directory(app_name=app_name, root=tmp, commit_sha=f"working:{base_ref}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    old_result = gqueries.load_current(driver, app_name)
    breaks = compute_breaks(old_result, new_result)
    impacts = resolve_impact(breaks, driver=driver, cmdb=cmdb)

    source_svc = cmdb.get(app_name) or {}
    source_platform = source_svc.get("platform")

    breaking = sum(1 for r in impacts if _is_breaking(r))
    info = len(impacts) - breaking
    cross_platform = sum(
        1 for r in impacts
        for a in r.impacted
        if source_platform and a.platform
        and a.platform != source_platform
        and a.platform != "library"
    )

    return {
        "app": app_name,
        "base_ref": base_ref,
        "source_platform": source_platform,
        "summary": {
            "breaking": breaking,
            "info": info,
            "affected_apps": sum(len(r.impacted) for r in impacts),
            "cross_platform": cross_platform,
        },
        "breaks": [_break_summary(r) for r in impacts],
        "overlay": {"written": written, "deleted": deleted},
    }


def _is_breaking(resolved) -> bool:
    """A resolved impact is 'breaking' if its kind is not in the info-only set."""
    from app.impact.diff import BREAK_SEVERITY
    return BREAK_SEVERITY.get(resolved.change.kind, "breaking") == "breaking"


def _break_summary(r) -> dict:
    d = asdict(r.change)
    d["impacted"] = [asdict(a) for a in r.impacted]
    return d
