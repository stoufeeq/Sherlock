"""Render the Sherlock-managed section of an app's README.

Most content is template-populated from the graph (which already knows the app's
contracts and dependencies) + CMDB (team / on-call / tier). An LLM pass is
called ONCE for the "Purpose" one-liner — so the model cost per repo is a single
short completion, not a per-file pass.

Output is wrapped in marker comments so existing hand-written README content
is preserved across regenerations.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from neo4j import Driver

from app.cmdb_client import CMDBClient
from app.llm.base import LLMProvider

SECTION_START = "<!-- sherlock:autodoc-start -->"
SECTION_END = "<!-- sherlock:autodoc-end -->"


@dataclass
class AutodocFacts:
    """Everything we learned about an app from the graph, ready for rendering."""
    app_name: str
    team: str | None
    tier: int | None
    on_call: str | None
    runtime: str | None
    repo_url: str | None
    commit_sha: str | None
    exposes_endpoints: list[tuple[str, str]]       # (method, path)
    publishes_topics: list[str]
    owned_schemas: list[str]
    written_tables: list[str]
    written_files: list[str]
    publishes_library: str | None
    calls_endpoints: list[tuple[str, str, str]]    # (target_app, method, path)
    consumed_topics: list[str]
    read_tables: list[str]
    read_files: list[str]
    library_deps: list[str]
    downstream_apps: list[str]                      # apps that would be affected by changes here
    upstream_apps: list[str]                        # apps this depends on


# ---- Fact gathering ----------------------------------------------------------

def gather_facts(driver: Driver, cmdb: CMDBClient, app_name: str) -> AutodocFacts:
    with driver.session() as s:
        app_row = s.run(
            "MATCH (a:Application {name:$n}) RETURN a.team AS team, a.tier AS tier, "
            "a.runtime AS runtime, a.repo_url AS repo_url, a.commit_sha AS commit_sha",
            n=app_name,
        ).single()
        if app_row is None:
            raise KeyError(f"application '{app_name}' not in graph")

        exposes = [
            (r["m"], r["p"])
            for r in s.run(
                "MATCH (:Application {name:$n})-[:EXPOSES]->(e:Endpoint) "
                "RETURN e.method AS m, e.path AS p ORDER BY p, m",
                n=app_name,
            )
        ]
        publishes = [
            r["t"] for r in s.run(
                "MATCH (:Application {name:$n})-[:PUBLISHES]->(t:Topic) "
                "RETURN t.name AS t ORDER BY t",
                n=app_name,
            )
        ]
        owned_schemas = [
            r["s"] for r in s.run(
                "MATCH (:Application {name:$n})-[:OWNS_SCHEMA]->(s:DBSchema) "
                "RETURN s.name AS s ORDER BY s", n=app_name,
            )
        ]
        written_tables = [
            r["f"] for r in s.run(
                "MATCH (:Application {name:$n})-[:WRITES_TABLE]->(t:DBTable) "
                "RETURN t.fqn AS f ORDER BY f", n=app_name,
            )
        ]
        written_files = [
            r["p"] for r in s.run(
                "MATCH (:Application {name:$n})-[:WRITES_FILE]->(f:FileFeed) "
                "RETURN f.path AS p ORDER BY p", n=app_name,
            )
        ]
        pub_lib_row = s.run(
            "MATCH (:Application {name:$n})-[:PUBLISHES_LIB]->(l:Library) "
            "RETURN l.gav AS g LIMIT 1", n=app_name,
        ).single()
        pub_lib = pub_lib_row["g"] if pub_lib_row else None

        calls = [
            (r["host"], r["m"], r["p"])
            for r in s.run(
                "MATCH (:Application {name:$n})-[:CALLS]->(e:Endpoint) "
                "RETURN e.host AS host, e.method AS m, e.path AS p "
                "ORDER BY host, p, m", n=app_name,
            )
            if r["host"] and r["host"] != app_name
        ]
        consumes = [
            r["t"] for r in s.run(
                "MATCH (:Application {name:$n})-[:CONSUMES]->(t:Topic) "
                "RETURN t.name AS t ORDER BY t", n=app_name,
            )
        ]
        read_tables = [
            r["f"] for r in s.run(
                "MATCH (:Application {name:$n})-[:READS_TABLE]->(t:DBTable) "
                "RETURN t.fqn AS f ORDER BY f", n=app_name,
            )
        ]
        read_files = [
            r["p"] for r in s.run(
                "MATCH (:Application {name:$n})-[:READS_FILE]->(f:FileFeed) "
                "RETURN f.path AS p ORDER BY p", n=app_name,
            )
        ]
        libs = [
            r["g"] for r in s.run(
                "MATCH (:Application {name:$n})-[:DEPENDS_ON_LIB]->(l:Library) "
                "RETURN l.gav AS g ORDER BY g", n=app_name,
            )
        ]
        # Downstream + upstream via one-hop graph traversal
        downstream = [
            r["name"] for r in s.run(
                """
                MATCH (src:Application {name:$n})
                CALL {
                  WITH src MATCH (src)-[:EXPOSES]->(:Endpoint)<-[:CALLS]-(d:Application) RETURN d
                  UNION WITH src MATCH (d:Application)-[:CALLS]->(:Endpoint {host:src.name}) RETURN d
                  UNION WITH src MATCH (src)-[:PUBLISHES]->(:Topic)<-[:CONSUMES]-(d:Application) RETURN d
                  UNION WITH src MATCH (src)-[:WRITES_TABLE]->(:DBTable)<-[:READS_TABLE]-(d:Application) RETURN d
                  UNION WITH src MATCH (src)-[:WRITES_FILE]->(:FileFeed)<-[:READS_FILE]-(d:Application) RETURN d
                  UNION WITH src MATCH (src)-[:PUBLISHES_LIB]->(:Library)<-[:DEPENDS_ON_LIB]-(d:Application) RETURN d
                }
                WITH DISTINCT d WHERE d.name <> $n AND coalesce(d.archived,false)=false
                RETURN d.name AS name ORDER BY name
                """, n=app_name,
            )
        ]
        upstream = [
            r["name"] for r in s.run(
                """
                MATCH (src:Application {name:$n})
                CALL {
                  WITH src MATCH (src)-[:CALLS]->(e:Endpoint)<-[:EXPOSES]-(d:Application) RETURN d
                  UNION WITH src MATCH (src)-[:CALLS]->(e:Endpoint) MATCH (d:Application {name:e.host}) RETURN d
                  UNION WITH src MATCH (src)-[:CONSUMES]->(:Topic)<-[:PUBLISHES]-(d:Application) RETURN d
                  UNION WITH src MATCH (src)-[:READS_TABLE]->(:DBTable)<-[:WRITES_TABLE]-(d:Application) RETURN d
                  UNION WITH src MATCH (src)-[:READS_FILE]->(:FileFeed)<-[:WRITES_FILE]-(d:Application) RETURN d
                  UNION WITH src MATCH (src)-[:DEPENDS_ON_LIB]->(:Library)<-[:PUBLISHES_LIB]-(d:Application) RETURN d
                }
                WITH DISTINCT d WHERE d.name <> $n AND coalesce(d.archived,false)=false
                RETURN d.name AS name ORDER BY name
                """, n=app_name,
            )
        ]

    svc = cmdb.get(app_name) or {}
    return AutodocFacts(
        app_name=app_name,
        team=svc.get("team") or app_row["team"],
        tier=svc.get("tier") if svc.get("tier") is not None else app_row["tier"],
        on_call=svc.get("on_call_slack"),
        runtime=svc.get("runtime") or app_row["runtime"],
        repo_url=app_row["repo_url"],
        commit_sha=app_row["commit_sha"],
        exposes_endpoints=exposes,
        publishes_topics=publishes,
        owned_schemas=owned_schemas,
        written_tables=written_tables,
        written_files=written_files,
        publishes_library=pub_lib,
        calls_endpoints=calls,
        consumed_topics=consumes,
        read_tables=read_tables,
        read_files=read_files,
        library_deps=libs,
        downstream_apps=downstream,
        upstream_apps=upstream,
    )


# ---- Rendering ---------------------------------------------------------------

def _bullet_list(items: list, empty: str = "_none_") -> str:
    if not items:
        return f"- {empty}"
    return "\n".join(f"- `{i}`" for i in items)


def _endpoint_list(endpoints: list[tuple[str, str]], empty: str = "_none_") -> str:
    if not endpoints:
        return f"- {empty}"
    return "\n".join(f"- `{m} {p}`" for m, p in endpoints)


def _call_list(calls: list[tuple[str, str, str]], empty: str = "_none_") -> str:
    if not calls:
        return f"- {empty}"
    return "\n".join(f"- `{m} {p}`  →  **{host}**" for host, m, p in calls)


def _purpose_prompt(facts: AutodocFacts) -> str:
    return (
        f"Summarize in ONE concise sentence what the following application does, "
        f"based only on the evidence below. Do not speculate.\n\n"
        f"app: {facts.app_name}\n"
        f"runtime: {facts.runtime}\n"
        f"team: {facts.team}\n"
        f"exposes: {[f'{m} {p}' for m,p in facts.exposes_endpoints]}\n"
        f"publishes topics: {facts.publishes_topics}\n"
        f"writes tables: {facts.written_tables}\n"
        f"writes files: {facts.written_files}\n"
        f"calls: {[f'{h} {m} {p}' for h,m,p in facts.calls_endpoints]}\n"
        f"consumes topics: {facts.consumed_topics}\n\n"
        "Return ONE plain-English sentence, no markdown, no quotes. "
        "Requested output: one-sentence purpose."
    )


def render_section(facts: AutodocFacts, llm: LLMProvider) -> str:
    """Return the Sherlock-managed markdown block (including the begin/end markers)."""
    # 2048 gives reasoning-capable models (Gemini 2.5, o-series) enough headroom
    # for internal thinking tokens; actual emitted prose is still one sentence.
    purpose_resp = llm.complete(_purpose_prompt(facts), max_tokens=2048)
    purpose = purpose_resp.text.strip() or f"{facts.app_name} application."
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines: list[str] = [SECTION_START]
    lines.append("")
    lines.append("## 🔎 Auto-generated by Sherlock")
    lines.append("")
    lines.append(f"> _This block is maintained by **Sherlock** — the Dependency Intelligence Platform. "
                 f"Edits inside the markers will be overwritten on the next regeneration. "
                 f"Edit outside the markers to keep your content._")
    lines.append("")
    lines.append(f"**Purpose** — {purpose}")
    lines.append("")

    # Ownership
    lines.append("### Ownership")
    meta_rows = [
        ("Team", facts.team),
        ("Tier", facts.tier),
        ("On-call", facts.on_call),
        ("Runtime", facts.runtime),
        ("Last scanned commit", facts.commit_sha[:12] if facts.commit_sha else None),
    ]
    lines.append("| Field | Value |")
    lines.append("|---|---|")
    for k, v in meta_rows:
        val = f"`{v}`" if v is not None and v != "" else "_unknown_"
        lines.append(f"| {k} | {val} |")
    lines.append("")

    # What this app provides
    lines.append("### What this application provides")
    lines.append("")
    lines.append("**REST endpoints exposed**")
    lines.append(_endpoint_list(facts.exposes_endpoints))
    lines.append("")
    lines.append("**Events published**")
    lines.append(_bullet_list(facts.publishes_topics))
    lines.append("")
    lines.append("**Database schemas owned**")
    lines.append(_bullet_list(facts.owned_schemas))
    lines.append("")
    lines.append("**Database tables written**")
    lines.append(_bullet_list(facts.written_tables))
    lines.append("")
    lines.append("**Shared file feeds written**")
    lines.append(_bullet_list(facts.written_files))
    lines.append("")
    if facts.publishes_library:
        lines.append(f"**Published library** — `{facts.publishes_library}`")
        lines.append("")

    # What this app depends on
    lines.append("### What this application depends on")
    lines.append("")
    lines.append("**REST calls**")
    lines.append(_call_list(facts.calls_endpoints))
    lines.append("")
    lines.append("**Events consumed**")
    lines.append(_bullet_list(facts.consumed_topics))
    lines.append("")
    lines.append("**Database tables read**")
    lines.append(_bullet_list(facts.read_tables))
    lines.append("")
    lines.append("**Shared file feeds read**")
    lines.append(_bullet_list(facts.read_files))
    lines.append("")
    lines.append("**Library dependencies**")
    lines.append(_bullet_list(facts.library_deps[:20]))  # cap noise
    if len(facts.library_deps) > 20:
        lines.append(f"- … and {len(facts.library_deps) - 20} more")
    lines.append("")

    # Impact
    lines.append("### Cross-application impact")
    lines.append("")
    lines.append(f"**Changes here may affect ({len(facts.downstream_apps)})**")
    lines.append(_bullet_list(facts.downstream_apps, empty="_nothing known to depend on this app_"))
    lines.append("")
    lines.append(f"**This app depends on ({len(facts.upstream_apps)})**")
    lines.append(_bullet_list(facts.upstream_apps, empty="_no upstream dependencies detected_"))
    lines.append("")

    lines.append("---")
    lines.append(f"_Generated {now} · model: `{purpose_resp.provider}/{purpose_resp.model}` · "
                 f"scanned commit: `{(facts.commit_sha or 'unknown')[:12]}`_")
    lines.append("")
    lines.append(SECTION_END)
    return "\n".join(lines)


def merge_into_readme(existing: str | None, generated_section: str) -> str:
    """Replace the Sherlock-managed block in `existing`, or append if not present.

    If `existing` is empty/None, return a new README with just our block and a
    placeholder heading so the file isn't weirdly headless.
    """
    if not existing or not existing.strip():
        return (
            "# (repo)\n\n"
            "_Add your team's description above this line. "
            "The block below is maintained by Sherlock — do not edit between the markers._\n\n"
            f"{generated_section}\n"
        )

    start = existing.find(SECTION_START)
    end = existing.find(SECTION_END)
    if start != -1 and end != -1 and end > start:
        end_full = end + len(SECTION_END)
        return existing[:start] + generated_section + existing[end_full:]
    # no marker yet — append to the end with a separator
    sep = "" if existing.endswith("\n\n") else ("\n\n" if existing.endswith("\n") else "\n\n")
    return existing + sep + generated_section + "\n"
