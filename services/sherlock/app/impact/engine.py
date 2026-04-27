"""For each BreakingChange, resolve the set of apps affected and the CMDB metadata we need
to route the notification (team, on-call channel, tier)."""

from dataclasses import dataclass

from neo4j import Driver

from app.cmdb_client import CMDBClient
from app.graph import queries
from app.impact.diff import BreakingChange


@dataclass(frozen=True)
class ImpactedApp:
    name: str
    team: str | None
    tier: int | None
    on_call_slack: str | None
    confidence: str           # "exact" | "heuristic"
    platform: str | None = None  # azure / on-prem / library — for cross-boundary callouts


@dataclass
class ResolvedImpact:
    change: BreakingChange
    impacted: list[ImpactedApp]


def resolve(
    changes: list[BreakingChange],
    *,
    driver: Driver,
    cmdb: CMDBClient,
) -> list[ResolvedImpact]:
    # Cache CMDB lookups per app within one MR analysis
    cmdb_cache: dict[str, dict] = {}

    def cmdb_for(name: str) -> dict:
        if name not in cmdb_cache:
            cmdb_cache[name] = cmdb.get(name) or {}
        return cmdb_cache[name]

    def to_impacted(names: list[str], confidence: str) -> list[ImpactedApp]:
        out: list[ImpactedApp] = []
        for n in names:
            svc = cmdb_for(n)
            out.append(
                ImpactedApp(
                    name=n,
                    team=svc.get("team"),
                    tier=svc.get("tier"),
                    on_call_slack=svc.get("on_call_slack"),
                    platform=svc.get("platform"),
                    confidence=confidence,
                )
            )
        return out

    results: list[ResolvedImpact] = []
    for change in changes:
        apps: list[ImpactedApp] = []

        if change.kind in (
            "endpoint_removed",
            "endpoint_schema_changed",
            "endpoint_schema_extended",
            "deprecated_endpoint_removed",
        ) and change.endpoint:
            method, path = change.endpoint
            exact = queries.callers_of_endpoint(driver, change.target_app, method, path)
            heuristic = queries.callers_of_app(driver, change.target_app)
            apps = to_impacted(exact, "exact")
            apps += to_impacted([n for n in heuristic if n not in set(exact)], "heuristic")

        elif change.kind in (
            "topic_publish_removed",
            "topic_payload_changed",
            "topic_payload_extended",
        ) and change.topic:
            apps = to_impacted(queries.consumers_of_topic(driver, change.topic), "exact")

        elif change.kind == "topic_consume_removed":
            # Not a cross-app break — only affects the app itself. Report with no downstream.
            apps = []

        elif change.kind == "table_write_removed" and change.table_fqn:
            apps = to_impacted(queries.readers_of_table(driver, change.table_fqn), "exact")

        elif change.kind == "schema_unowned" and change.schema:
            apps = to_impacted(queries.readers_of_schema(driver, change.schema), "exact")

        elif change.kind == "lib_published_removed" and change.library_gav:
            apps = to_impacted(queries.dependents_of_library(driver, change.library_gav), "exact")

        elif change.kind == "file_write_removed" and change.file_path:
            apps = to_impacted(queries.readers_of_file(driver, change.file_path), "exact")

        results.append(ResolvedImpact(change=change, impacted=apps))

    return results
