"""Render a markdown MR comment from resolved impact results."""

from app.impact.diff import BREAK_SEVERITY
from app.impact.engine import ImpactedApp, ResolvedImpact

COMMENT_MARKER = "<!-- sherlock-impact-v1 -->"

KIND_HEADLINE = {
    "endpoint_removed":             "Removed REST endpoint",
    "endpoint_schema_changed":      "REST endpoint required-fields contract changed",
    "endpoint_schema_extended":     "REST endpoint extended (new optional field) — additive",
    "deprecated_endpoint_removed":  "Removed REST endpoint that was already marked deprecated",
    "topic_publish_removed":        "Stopped publishing topic",
    "topic_consume_removed":        "Stopped consuming topic",
    "topic_payload_changed":        "Topic payload required-fields contract changed",
    "topic_payload_extended":       "Topic payload extended (new optional field) — additive",
    "table_write_removed":          "Stopped writing table",
    "schema_unowned":               "Released ownership of schema",
    "lib_published_removed":        "Published library identity changed",
    "file_write_removed":           "Stopped writing shared file feed",
}

KIND_ICON = {
    "endpoint_removed":             "🔌",
    "endpoint_schema_changed":      "🧬",
    "endpoint_schema_extended":     "➕",
    "deprecated_endpoint_removed":  "🪦",
    "topic_publish_removed":        "📤",
    "topic_consume_removed":        "📥",
    "topic_payload_changed":        "🧬",
    "topic_payload_extended":       "➕",
    "table_write_removed":          "🗄️",
    "schema_unowned":               "🗂️",
    "lib_published_removed":        "📦",
    "file_write_removed":           "📄",
}


def _fmt_app(a: ImpactedApp) -> str:
    team = f"team: `{a.team}`" if a.team else "team: _unknown_"
    tier = f"tier {a.tier}" if a.tier is not None else "tier _?_"
    channel = f"on-call: `{a.on_call_slack}`" if a.on_call_slack else "on-call: _unknown_"
    tag = "" if a.confidence == "exact" else " _(heuristic match)_"
    return f"- **`{a.name}`** ({team} · {tier} · {channel}){tag}"


def render_comment(
    *,
    source_app: str,
    source_commit: str,
    target_branch: str,
    impacts: list[ResolvedImpact],
) -> str:
    """Return the full markdown body of the MR comment."""
    lines: list[str] = []
    lines.append(COMMENT_MARKER)
    lines.append("## 🔎 Sherlock Impact Analysis")
    lines.append("")
    lines.append(f"Source app: `{source_app}`  ·  commit `{source_commit[:8]}`  ·  target branch `{target_branch}`")
    lines.append("")

    if not impacts:
        lines.append("✅ **No cross-application breaking changes detected.**")
        lines.append("")
        lines.append("This change doesn't remove any exposed endpoints, published topics, or written tables "
                     "that other apps rely on.")
        lines.append("")
        lines.append("---")
        lines.append("_Sherlock informs — it does not block merges._")
        return "\n".join(lines)

    breaking_count = sum(1 for r in impacts if BREAK_SEVERITY.get(r.change.kind) == "breaking")
    info_count = len(impacts) - breaking_count
    if breaking_count:
        lines.append(f"⚠️ **{breaking_count} breaking change(s) detected**"
                     + (f" + {info_count} additive/info-only change(s)" if info_count else "")
                     + " — potential cross-application impact below.")
    else:
        lines.append(f"ℹ️ **{info_count} additive / info-only change(s) detected**"
                     " — no required contracts removed; consumers should not break.")
    lines.append("")

    for r in impacts:
        icon = KIND_ICON.get(r.change.kind, "❗")
        headline = KIND_HEADLINE.get(r.change.kind, r.change.kind)
        sev = BREAK_SEVERITY.get(r.change.kind, "breaking")
        sev_badge = " _(info — non-breaking)_" if sev == "info" else ""
        lines.append(f"### {icon} {headline}: `{r.change.detail}`{sev_badge}")
        lines.append("")

        if not r.impacted:
            lines.append("_No known downstream consumers in the current graph._")
            lines.append("")
            continue

        exact = [a for a in r.impacted if a.confidence == "exact"]
        heuristic = [a for a in r.impacted if a.confidence == "heuristic"]

        if exact:
            lines.append(f"**Directly affected ({len(exact)}):**")
            for a in exact:
                lines.append(_fmt_app(a))
            lines.append("")
        if heuristic:
            lines.append(f"**Potentially affected ({len(heuristic)}):**  _matched by host, not by specific path_")
            for a in heuristic:
                lines.append(_fmt_app(a))
            lines.append("")

    lines.append("---")
    lines.append("_Sherlock informs — it does not block merges. "
                 "Coordinate with the teams above before merging, or acknowledge and proceed._")
    return "\n".join(lines)
