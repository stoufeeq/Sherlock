"""Read-only HTTP surface the UI talks to — Cytoscape-formatted graph + impact queries."""

import asyncio
from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request

from app.config import settings

router = APIRouter(prefix="/api", tags=["graph"])

# Node-label colors and short codes used by the UI
NODE_KINDS = {
    "Application": {"code": "app", "color": "#4f46e5"},
    "Endpoint":    {"code": "ep",  "color": "#10b981"},
    "Topic":       {"code": "tpc", "color": "#f59e0b"},
    "DBSchema":    {"code": "sch", "color": "#8b5cf6"},
    "DBTable":     {"code": "tbl", "color": "#a855f7"},
    "Library":     {"code": "lib", "color": "#64748b"},
    "FileFeed":    {"code": "ff",  "color": "#14b8a6"},
}

# Relationship -> visual weight / dashing for the UI
EDGE_KINDS = [
    "EXPOSES", "CALLS", "PUBLISHES", "CONSUMES",
    "DEPENDS_ON_LIB", "PUBLISHES_LIB",
    "OWNS_SCHEMA", "READS_TABLE", "WRITES_TABLE", "CONTAINS_TABLE",
    "READS_FILE", "WRITES_FILE",
]


def _node_id(label: str, key: str) -> str:
    return f"{NODE_KINDS[label]['code']}:{key}"


def _app_key(n) -> str:
    return n["name"]


def _fetch_all(driver, *, include_archived: bool = False) -> dict:
    nodes: list[dict] = []
    edges: list[dict] = []
    seen_ids: set[str] = set()

    def add_node(label: str, key: str, props: dict) -> str:
        nid = _node_id(label, key)
        if nid not in seen_ids:
            seen_ids.add(nid)
            nodes.append({"data": {"id": nid, "label": label, **props}})
        return nid

    app_filter = "" if include_archived else "WHERE coalesce(a.archived, false) = false"

    with driver.session() as s:
        # Applications — source of truth for the top-level nodes
        for row in s.run(
            f"MATCH (a:Application) {app_filter} "
            "RETURN a.name AS name, a.team AS team, a.tier AS tier, "
            "a.runtime AS runtime, a.platform AS platform, "
            "a.repo_url AS repo_url, a.commit_sha AS commit_sha, "
            "a.project_id AS project_id, coalesce(a.archived, false) AS archived, "
            "a.renamed_to AS renamed_to"
        ):
            add_node("Application", row["name"], {
                "name": row["name"],
                "team": row["team"],
                "tier": row["tier"],
                "runtime": row["runtime"],
                "platform": row["platform"],
                "repo_url": row["repo_url"],
                "commit_sha": row["commit_sha"],
                "project_id": row["project_id"],
                "archived": row["archived"],
                "renamed_to": row["renamed_to"],
            })

        # Endpoints
        for row in s.run(
            "MATCH (e:Endpoint) RETURN e.id AS id, e.method AS method, e.path AS path, e.host AS host"
        ):
            add_node("Endpoint", row["id"], {
                "name": f"{row['method']} {row['path']}",
                "method": row["method"],
                "path": row["path"],
                "host": row["host"],
            })

        # Topics
        for row in s.run("MATCH (t:Topic) RETURN t.name AS name"):
            add_node("Topic", row["name"], {"name": row["name"]})

        # Schemas
        for row in s.run("MATCH (s:DBSchema) RETURN s.name AS name"):
            add_node("DBSchema", row["name"], {"name": row["name"]})

        # Tables
        for row in s.run(
            "MATCH (t:DBTable) RETURN t.fqn AS fqn, t.name AS name, t.schema AS schema"
        ):
            add_node("DBTable", row["fqn"], {
                "name": row["fqn"], "table": row["name"], "schema": row["schema"],
            })

        # Libraries
        for row in s.run("MATCH (l:Library) RETURN l.gav AS gav"):
            add_node("Library", row["gav"], {"name": row["gav"]})

        # File feeds (shared-filesystem paths)
        for row in s.run(
            "MATCH (f:FileFeed) RETURN f.path AS path, f.extension AS extension"
        ):
            add_node("FileFeed", row["path"], {
                "name": row["path"], "path": row["path"], "extension": row["extension"],
            })

        # All edges — we map their endpoint IDs to our prefixed node IDs.
        # `via_gateway` is only set on CALLS relationships rewritten by the
        # API-gateway resolver; the canvas uses it to dash + tint those edges.
        q = """
        MATCH (x)-[r]->(y)
        WHERE type(r) IN $kinds
        RETURN
          labels(x)[0] AS x_label,
          coalesce(x.name, x.gav, x.fqn, x.id, x.path) AS x_key,
          labels(y)[0] AS y_label,
          coalesce(y.name, y.gav, y.fqn, y.id, y.path) AS y_key,
          type(r) AS kind,
          r.via_gateway AS via_gateway
        """
        for i, row in enumerate(s.run(q, kinds=EDGE_KINDS)):
            src = _node_id(row["x_label"], row["x_key"])
            tgt = _node_id(row["y_label"], row["y_key"])
            data = {"id": f"e{i}", "source": src, "target": tgt, "kind": row["kind"]}
            if row.get("via_gateway"):
                data["via_gateway"] = row["via_gateway"]
            edges.append({"data": data})

    return {"nodes": nodes, "edges": edges}


@router.get("/graph")
def graph(request: Request, include_archived: bool = False) -> dict:
    driver = request.app.state.graph.driver
    g = _fetch_all(driver, include_archived=include_archived)
    g["stats"] = {
        "nodes_total": len(g["nodes"]),
        "edges_total": len(g["edges"]),
        "by_label": {},
        "by_kind": {},
    }
    for n in g["nodes"]:
        lbl = n["data"]["label"]
        g["stats"]["by_label"][lbl] = g["stats"]["by_label"].get(lbl, 0) + 1
    for e in g["edges"]:
        k = e["data"]["kind"]
        g["stats"]["by_kind"][k] = g["stats"]["by_kind"].get(k, 0) + 1
    return g


@router.get("/apps")
def apps(request: Request, include_archived: bool = True) -> list[dict]:
    """List Applications with summary edge counts + archival metadata.

    By default returns BOTH active and archived apps — the UI filters. The
    graph views (/api/graph, /api/app-graph) default to excluding archived.
    """
    driver = request.app.state.graph.driver
    with driver.session() as s:
        rows = s.run(
            """
            MATCH (a:Application)
            OPTIONAL MATCH (a)-[:EXPOSES]->(e:Endpoint)
            OPTIONAL MATCH (a)-[:CALLS]->(ce:Endpoint)
            OPTIONAL MATCH (a)-[:PUBLISHES]->(pt:Topic)
            OPTIONAL MATCH (a)-[:CONSUMES]->(ct:Topic)
            RETURN a.name AS name,
                   a.team AS team,
                   a.tier AS tier,
                   a.runtime AS runtime,
                   a.platform AS platform,
                   a.commit_sha AS commit_sha,
                   a.project_id AS project_id,
                   coalesce(a.archived, false) AS archived,
                   a.archived_at AS archived_at,
                   a.renamed_to AS renamed_to,
                   count(DISTINCT e)  AS exposes,
                   count(DISTINCT ce) AS calls,
                   count(DISTINCT pt) AS publishes,
                   count(DISTINCT ct) AS consumes
            ORDER BY coalesce(a.archived, false), a.tier, a.name
            """
        )
        out = [dict(r) for r in rows]
        if not include_archived:
            out = [r for r in out if not r["archived"]]
        # Neo4j datetime objects need stringification
        for r in out:
            if r.get("archived_at") is not None:
                r["archived_at"] = str(r["archived_at"])
        return out


@router.get("/app-graph")
def app_graph(request: Request, include_archived: bool = False) -> dict:
    """App-to-app only — collapses endpoints/topics/tables/libs into labelled direct edges.

    Edge direction: consumer → producer (so with rankDir=BT, producers sit above consumers).
    Archived apps are excluded by default; pass include_archived=true to include them.
    """
    driver = request.app.state.graph.driver
    nodes: list[dict] = []
    edges: list[dict] = []
    seen_node_ids: set[str] = set()

    def add_app(n) -> str:
        nid = _node_id("Application", n["name"])
        if nid not in seen_node_ids:
            seen_node_ids.add(nid)
            nodes.append({"data": {"id": nid, "label": "Application", **n}})
        return nid

    app_filter = "" if include_archived else "WHERE coalesce(a.archived, false) = false"

    with driver.session() as s:
        for row in s.run(
            f"MATCH (a:Application) {app_filter} "
            "RETURN a.name AS name, a.team AS team, a.tier AS tier, "
            "a.runtime AS runtime, a.platform AS platform, "
            "a.repo_url AS repo_url, a.commit_sha AS commit_sha, "
            "a.project_id AS project_id, coalesce(a.archived, false) AS archived"
        ):
            add_app(dict(row))

        # REST: consumer -[CALLS]-> endpoint <-[EXPOSES]- producer
        # `via_gateway` (when set) means the resolver rewrote a gateway URL — the
        # canvas can colour the edge differently to make the indirection visible.
        for i, row in enumerate(s.run(
            """
            MATCH (a:Application)-[r:CALLS]->(e:Endpoint)<-[:EXPOSES]-(b:Application)
            WHERE a.name <> b.name
            RETURN a.name AS consumer, b.name AS producer,
                   e.method AS method, e.path AS path,
                   r.via_gateway AS via_gateway
            """
        )):
            via = row.get("via_gateway")
            label = f"{row['method']} {row['path']}"
            if via:
                label += f"  (via {via})"
            edges.append({"data": {
                "id": f"rest-{i}",
                "source": _node_id("Application", row["consumer"]),
                "target": _node_id("Application", row["producer"]),
                "kind": "REST",
                "label": label,
                "via_gateway": via,
            }})

        # REST host-only fallback: consumer -[CALLS]-> endpoint{host:X} when no matching EXPOSES
        for i, row in enumerate(s.run(
            """
            MATCH (a:Application)-[r:CALLS]->(e:Endpoint)
            WHERE NOT ( ()-[:EXPOSES]->(e) )
              AND e.host IS NOT NULL
              AND e.host <> a.name
            MATCH (b:Application {name: e.host})
            RETURN a.name AS consumer, b.name AS producer,
                   e.method AS method, e.path AS path,
                   r.via_gateway AS via_gateway
            """
        )):
            via = row.get("via_gateway")
            label = f"{row['method']} {row['path']} (host-only)"
            if via:
                label += f"  (via {via})"
            edges.append({"data": {
                "id": f"rest-h-{i}",
                "source": _node_id("Application", row["consumer"]),
                "target": _node_id("Application", row["producer"]),
                "kind": "REST",
                "label": label,
                "via_gateway": via,
            }})

        # EVENT: consumer -[CONSUMES]-> topic <-[PUBLISHES]- producer
        for i, row in enumerate(s.run(
            """
            MATCH (a:Application)-[:CONSUMES]->(t:Topic)<-[:PUBLISHES]-(b:Application)
            WHERE a.name <> b.name
            RETURN a.name AS consumer, b.name AS producer, t.name AS topic
            """
        )):
            edges.append({"data": {
                "id": f"evt-{i}",
                "source": _node_id("Application", row["consumer"]),
                "target": _node_id("Application", row["producer"]),
                "kind": "EVENT",
                "label": row["topic"],
            }})

        # DB: reader -[READS_TABLE]-> table <-[WRITES_TABLE]- writer
        for i, row in enumerate(s.run(
            """
            MATCH (a:Application)-[:READS_TABLE]->(t:DBTable)<-[:WRITES_TABLE]-(b:Application)
            WHERE a.name <> b.name
            RETURN a.name AS reader, b.name AS writer, t.fqn AS fqn
            """
        )):
            edges.append({"data": {
                "id": f"db-{i}",
                "source": _node_id("Application", row["reader"]),
                "target": _node_id("Application", row["writer"]),
                "kind": "DB",
                "label": f"reads {row['fqn']}",
            }})

        # LIB: dependent -[DEPENDS_ON_LIB]-> lib <-[PUBLISHES_LIB]- publisher
        for i, row in enumerate(s.run(
            """
            MATCH (a:Application)-[:DEPENDS_ON_LIB]->(l:Library)<-[:PUBLISHES_LIB]-(b:Application)
            WHERE a.name <> b.name
            RETURN a.name AS dependent, b.name AS publisher, l.gav AS gav
            """
        )):
            edges.append({"data": {
                "id": f"lib-{i}",
                "source": _node_id("Application", row["dependent"]),
                "target": _node_id("Application", row["publisher"]),
                "kind": "LIB",
                "label": row["gav"],
            }})

        # FILE: reader -[READS_FILE]-> feed <-[WRITES_FILE]- writer
        for i, row in enumerate(s.run(
            """
            MATCH (a:Application)-[:READS_FILE]->(f:FileFeed)<-[:WRITES_FILE]-(b:Application)
            WHERE a.name <> b.name
            RETURN a.name AS reader, b.name AS writer, f.path AS path
            """
        )):
            edges.append({"data": {
                "id": f"file-{i}",
                "source": _node_id("Application", row["reader"]),
                "target": _node_id("Application", row["writer"]),
                "kind": "FILE",
                "label": f"reads {row['path']}",
            }})

    # Stats: count edges by kind
    by_kind: dict[str, int] = {}
    for e in edges:
        k = e["data"]["kind"]
        by_kind[k] = by_kind.get(k, 0) + 1

    return {
        "nodes": nodes,
        "edges": edges,
        "stats": {"apps": len(nodes), "edges_total": len(edges), "by_kind": by_kind},
    }


@router.get("/reconciler/status")
def reconciler_status(request: Request) -> dict:
    state = request.app.state.reconciler
    return {
        "enabled": settings.reconcile_enabled,
        "interval_seconds": settings.reconcile_interval_seconds,
        "groups": settings.groups_list,
        "running_now": state.running_now,
        "last_run": asdict(state.last_run) if state.last_run else None,
        "history": [asdict(r) for r in list(state.last_runs)],
    }


@router.post("/autodoc/trigger/{app_name}")
async def autodoc_trigger(app_name: str, request: Request) -> dict:
    """Manually regenerate the Sherlock-managed README section for one app.
    Opens (or refreshes) a draft MR labeled `sherlock::autodoc` in that repo."""
    from app.autodoc.workflow import run_autodoc_for_app
    from app.scan_service import project_lookup
    project = project_lookup(request.app.state.gitlab).get(app_name)
    if project is None:
        raise HTTPException(status_code=404, detail=f"app '{app_name}' not in any configured group")
    outcome = await asyncio.to_thread(
        run_autodoc_for_app,
        app_name=app_name,
        project=project,
        graph=request.app.state.graph,
        cmdb=request.app.state.cmdb,
        gitlab=request.app.state.gitlab,
        llm=request.app.state.llm,
    )
    return asdict(outcome)


@router.post("/reconciler/trigger")
async def reconciler_trigger(request: Request) -> dict:
    """Kick off a reconciliation immediately (useful for demo / after adding a project)."""
    from app.reconciler import reconcile_once_sync
    state = request.app.state.reconciler
    if state.running_now:
        raise HTTPException(status_code=409, detail="reconciler is already running")
    state.running_now = True
    try:
        run = await asyncio.to_thread(
            reconcile_once_sync,
            request.app.state.gitlab,
            request.app.state.graph,
            request.app.state.cmdb,
        )
        state.last_run = run
        state.last_runs.append(run)
    finally:
        state.running_now = False
    return asdict(run)


# Per-hop edge templates. Each query takes a list of source app names ($names)
# and returns the set of apps reachable in ONE hop in the given direction. The
# multi-hop walk in /impact does N rounds of these, expanding the visited set.
_DOWNSTREAM_HOP_CYPHER = """
UNWIND $names AS srcname
MATCH (src:Application {name: srcname})
CALL {
  WITH src
  MATCH (src)-[:EXPOSES]->(:Endpoint)<-[:CALLS]-(d:Application) RETURN d
  UNION
  WITH src
  MATCH (d:Application)-[:CALLS]->(:Endpoint {host:src.name}) RETURN d
  UNION
  WITH src
  MATCH (src)-[:PUBLISHES]->(:Topic)<-[:CONSUMES]-(d:Application) RETURN d
  UNION
  WITH src
  MATCH (src)-[:WRITES_TABLE]->(:DBTable)<-[:READS_TABLE]-(d:Application) RETURN d
  UNION
  WITH src
  MATCH (src)-[:PUBLISHES_LIB]->(:Library)<-[:DEPENDS_ON_LIB]-(d:Application) RETURN d
  UNION
  WITH src
  MATCH (src)-[:WRITES_FILE]->(:FileFeed)<-[:READS_FILE]-(d:Application) RETURN d
}
WITH DISTINCT d
WHERE NOT d.name IN $visited
RETURN d.name AS name ORDER BY name
"""

_UPSTREAM_HOP_CYPHER = """
UNWIND $names AS srcname
MATCH (src:Application {name: srcname})
CALL {
  WITH src
  MATCH (src)-[:CALLS]->(:Endpoint)<-[:EXPOSES]-(d:Application) RETURN d
  UNION
  WITH src
  MATCH (src)-[:CALLS]->(e:Endpoint) MATCH (d:Application {name:e.host}) RETURN d
  UNION
  WITH src
  MATCH (src)-[:CONSUMES]->(:Topic)<-[:PUBLISHES]-(d:Application) RETURN d
  UNION
  WITH src
  MATCH (src)-[:READS_TABLE]->(:DBTable)<-[:WRITES_TABLE]-(d:Application) RETURN d
  UNION
  WITH src
  MATCH (src)-[:DEPENDS_ON_LIB]->(:Library)<-[:PUBLISHES_LIB]-(d:Application) RETURN d
  UNION
  WITH src
  MATCH (src)-[:READS_FILE]->(:FileFeed)<-[:WRITES_FILE]-(d:Application) RETURN d
}
WITH DISTINCT d
WHERE NOT d.name IN $visited
RETURN d.name AS name ORDER BY name
"""

# Hard ceiling on how deep the BFS will walk — a runaway query in a 50k-node
# graph could iterate forever otherwise. 10 is well past anything anyone wants
# in a UI; the MR-bot only ever uses depth 1.
_MAX_DEPTH = 10


@router.get("/impact/{app_name}")
def impact(app_name: str, request: Request, direction: str = "downstream", depth: int = 1) -> dict:
    """Return apps affected by changes in `app_name`, walked up to `depth` hops.

    `depth=1` (default) is the original single-hop behaviour the MR bot uses.
    Higher depths surface 2nd-, 3rd-order blast radius for the canvas overlay
    and for "but what about the apps that depend on the apps I depend on?"
    questions. The response includes a `by_hop` breakdown so the caller can
    distinguish immediate from indirect impact.
    """
    if direction not in {"downstream", "upstream"}:
        raise HTTPException(status_code=400, detail="direction must be downstream|upstream")
    if depth < 1 or depth > _MAX_DEPTH:
        raise HTTPException(status_code=400, detail=f"depth must be 1..{_MAX_DEPTH}")
    driver = request.app.state.graph.driver
    cypher = _DOWNSTREAM_HOP_CYPHER if direction == "downstream" else _UPSTREAM_HOP_CYPHER

    visited: set[str] = {app_name}
    frontier: list[str] = [app_name]
    by_hop: list[dict] = []
    with driver.session() as s:
        for hop in range(1, depth + 1):
            if not frontier:
                break
            new_apps = [
                row["name"] for row in s.run(cypher, names=frontier, visited=list(visited))
            ]
            by_hop.append({"hop": hop, "apps": new_apps})
            if not new_apps:
                break
            visited.update(new_apps)
            frontier = new_apps

    affected = sorted(visited - {app_name})
    return {
        "app": app_name,
        "direction": direction,
        "depth": depth,
        "max_hop_reached": by_hop[-1]["hop"] if by_hop else 0,
        "affected_apps": affected,
        "by_hop": by_hop,
    }
