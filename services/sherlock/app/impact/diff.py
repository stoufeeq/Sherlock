"""Compute a list of BreakingChanges by comparing two AnalysisResults for the same app."""

from dataclasses import dataclass
from typing import Literal

from app.models import AnalysisResult

BreakKind = Literal[
    "endpoint_removed",
    "endpoint_schema_changed",
    "endpoint_schema_extended",      # additive (new optional REST field) — info-level
    "deprecated_endpoint_removed",   # endpoint was already marked deprecated — low severity
    "topic_publish_removed",
    "topic_consume_removed",
    "topic_payload_changed",         # required-field-bearing payload change — breaking
    "topic_payload_extended",        # additive (new optional event field) — info-level
    "table_write_removed",
    "schema_unowned",
    "lib_published_removed",
    "file_write_removed",
]


# Severity: 'breaking' affects consumers and warrants action; 'info' is purely additive
# or an announced change consumers should already have prepared for.
BREAK_SEVERITY: dict[str, str] = {
    "endpoint_removed":             "breaking",
    "endpoint_schema_changed":      "breaking",
    "endpoint_schema_extended":     "info",
    "deprecated_endpoint_removed":  "info",
    "topic_publish_removed":        "breaking",
    "topic_consume_removed":        "breaking",
    "topic_payload_changed":        "breaking",
    "topic_payload_extended":       "info",
    "table_write_removed":          "breaking",
    "schema_unowned":               "breaking",
    "lib_published_removed":        "breaking",
    "file_write_removed":           "breaking",
}


@dataclass(frozen=True)
class BreakingChange:
    kind: BreakKind
    target_app: str
    detail: str
    # Break-kind-specific payload used by the impact engine to walk the graph:
    endpoint: tuple[str, str] | None = None  # (method, path)
    topic: str | None = None
    table_fqn: str | None = None
    schema: str | None = None
    library_gav: str | None = None
    file_path: str | None = None


def compute_breaks(old: AnalysisResult, new: AnalysisResult) -> list[BreakingChange]:
    if old.app_name != new.app_name:
        raise ValueError("can only diff AnalysisResults for the same app")

    app = new.app_name
    breaks: list[BreakingChange] = []

    # Endpoints removed (exposed in old, not in new) — downgrade severity if the
    # endpoint had already been marked `deprecated: true` in the previous spec.
    old_eps = {tuple(e) for e in old.exposed_endpoints}
    new_eps = {tuple(e) for e in new.exposed_endpoints}
    for method, path in sorted(old_eps - new_eps):
        was_deprecated = (method, path) in old.deprecated_endpoints
        kind: BreakKind = "deprecated_endpoint_removed" if was_deprecated else "endpoint_removed"
        breaks.append(
            BreakingChange(
                kind=kind,
                target_app=app,
                detail=f"{method} {path}",
                endpoint=(method, path),
            )
        )

    # Endpoints with changed schemas — distinguish breaking (required-fields delta)
    # from additive (only optional/extra fields changed).
    for method, path in sorted(old_eps & new_eps):
        key = (method, path)
        old_full = old.endpoint_shapes.get(key)
        new_full = new.endpoint_shapes.get(key)
        old_req = old.endpoint_required_shapes.get(key)
        new_req = new.endpoint_required_shapes.get(key)

        if old_full and new_full and old_full != new_full:
            # Something changed in the schema. Was it the required subset?
            required_changed = bool(old_req and new_req and old_req != new_req)
            kind = "endpoint_schema_changed" if required_changed else "endpoint_schema_extended"
            breaks.append(
                BreakingChange(
                    kind=kind,
                    target_app=app,
                    detail=f"{method} {path}",
                    endpoint=(method, path),
                )
            )

    # Topics no longer published
    for topic in sorted(set(old.published_topics) - set(new.published_topics)):
        breaks.append(
            BreakingChange(
                kind="topic_publish_removed",
                target_app=app,
                detail=topic,
                topic=topic,
            )
        )

    # Topics no longer consumed (own-side impact only — doesn't break downstream)
    for topic in sorted(set(old.consumed_topics) - set(new.consumed_topics)):
        breaks.append(
            BreakingChange(
                kind="topic_consume_removed",
                target_app=app,
                detail=topic,
                topic=topic,
            )
        )

    # Topic payload shape changed — distinguish breaking (required-fields delta)
    # from additive (only new optional fields).
    for topic in sorted(set(old.published_topics) & set(new.published_topics)):
        old_full = old.topic_shapes.get(topic)
        new_full = new.topic_shapes.get(topic)
        old_req = old.topic_required_shapes.get(topic)
        new_req = new.topic_required_shapes.get(topic)

        if old_full and new_full and old_full != new_full:
            required_changed = bool(old_req and new_req and old_req != new_req)
            kind: BreakKind = "topic_payload_changed" if required_changed else "topic_payload_extended"
            breaks.append(
                BreakingChange(
                    kind=kind,
                    target_app=app,
                    detail=topic,
                    topic=topic,
                )
            )

    # Tables we stopped writing (anyone reading loses their data source)
    for fqn in sorted(set(old.written_tables) - set(new.written_tables)):
        breaks.append(
            BreakingChange(
                kind="table_write_removed",
                target_app=app,
                detail=fqn,
                table_fqn=fqn,
            )
        )

    # Schemas we stopped owning
    for schema in sorted(set(old.owned_schemas) - set(new.owned_schemas)):
        breaks.append(
            BreakingChange(
                kind="schema_unowned",
                target_app=app,
                detail=schema,
                schema=schema,
            )
        )

    # Files we stopped writing (anyone reading this feed loses its source)
    for p in sorted(set(old.written_files) - set(new.written_files)):
        breaks.append(
            BreakingChange(
                kind="file_write_removed",
                target_app=app,
                detail=p,
                file_path=p,
            )
        )

    # Library coords changed (rename / retired)
    if old.library_published and old.library_published != new.library_published:
        breaks.append(
            BreakingChange(
                kind="lib_published_removed",
                target_app=app,
                detail=old.library_published,
                library_gav=old.library_published,
            )
        )

    return breaks
