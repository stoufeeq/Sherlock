"""Read-only queries used by the impact engine.

Kept separate from graph/client.py so the write path and the read path stay
clearly distinguishable.
"""

from neo4j import Driver

from app.models import AnalysisResult


def load_current(driver: Driver, app_name: str) -> AnalysisResult:
    """Build an AnalysisResult from whatever is in the graph RIGHT NOW for this app."""
    r = AnalysisResult(app_name=app_name, commit_sha="")
    with driver.session() as s:
        row = s.run(
            "MATCH (a:Application {name:$app}) RETURN a.commit_sha AS sha", app=app_name
        ).single()
        if row and row["sha"]:
            r.commit_sha = row["sha"]

        for row in s.run(
            "MATCH (:Application {name:$app})-[:EXPOSES]->(e:Endpoint) "
            "RETURN e.method AS m, e.path AS p, "
            "       e.req_hash AS req, e.res_hash AS res, "
            "       e.req_req_hash AS req_required, e.res_req_hash AS res_required, "
            "       coalesce(e.deprecated, false) AS deprecated",
            app=app_name,
        ):
            key = (row["m"], row["p"])
            r.exposed_endpoints.append(key)
            if row["req"] is not None or row["res"] is not None:
                r.endpoint_shapes[key] = (row["req"], row["res"])
            if row["req_required"] is not None or row["res_required"] is not None:
                r.endpoint_required_shapes[key] = (row["req_required"], row["res_required"])
            if row["deprecated"]:
                r.deprecated_endpoints.add(key)

        for row in s.run(
            "MATCH (:Application {name:$app})-[:PUBLISHES]->(t:Topic) "
            "RETURN t.name AS n, t.payload_hash AS h, t.payload_req_hash AS req",
            app=app_name,
        ):
            r.published_topics.append(row["n"])
            if row["h"] is not None:
                r.topic_shapes[row["n"]] = row["h"]
            if row["req"] is not None:
                r.topic_required_shapes[row["n"]] = row["req"]

        for row in s.run(
            "MATCH (:Application {name:$app})-[:CONSUMES]->(t:Topic) RETURN t.name AS n",
            app=app_name,
        ):
            r.consumed_topics.append(row["n"])

        for row in s.run(
            "MATCH (:Application {name:$app})-[:OWNS_SCHEMA]->(s:DBSchema) RETURN s.name AS n",
            app=app_name,
        ):
            r.owned_schemas.append(row["n"])

        for row in s.run(
            "MATCH (:Application {name:$app})-[:WRITES_TABLE]->(t:DBTable) RETURN t.fqn AS f",
            app=app_name,
        ):
            r.written_tables.append(row["f"])

        for row in s.run(
            "MATCH (:Application {name:$app})-[:READS_TABLE]->(t:DBTable) RETURN t.fqn AS f",
            app=app_name,
        ):
            r.read_tables.append(row["f"])

        for row in s.run(
            "MATCH (:Application {name:$app})-[:DEPENDS_ON_LIB]->(l:Library) RETURN l.gav AS g",
            app=app_name,
        ):
            r.library_deps.append(row["g"])

        row = s.run(
            "MATCH (:Application {name:$app})-[:PUBLISHES_LIB]->(l:Library) RETURN l.gav AS g",
            app=app_name,
        ).single()
        if row:
            r.library_published = row["g"]

        for row in s.run(
            "MATCH (:Application {name:$app})-[:READS_FILE]->(f:FileFeed) RETURN f.path AS p",
            app=app_name,
        ):
            r.read_files.append(row["p"])

        for row in s.run(
            "MATCH (:Application {name:$app})-[:WRITES_FILE]->(f:FileFeed) RETURN f.path AS p",
            app=app_name,
        ):
            r.written_files.append(row["p"])

    return r


def callers_of_endpoint(driver: Driver, host_app: str, method: str, path: str) -> list[str]:
    """Apps that call the specific endpoint (exact match on id)."""
    eid = f"{host_app}:{method}:{path}"
    with driver.session() as s:
        return [
            row["name"]
            for row in s.run(
                "MATCH (a:Application)-[:CALLS]->(e:Endpoint {id:$id}) RETURN DISTINCT a.name AS name ORDER BY name",
                id=eid,
            )
        ]


def callers_of_app(driver: Driver, host_app: str) -> list[str]:
    """Apps that call ANY endpoint hosted by host_app (via the catch-all path too).

    Useful fallback when we can't precisely match a changed endpoint.
    """
    with driver.session() as s:
        return [
            row["name"]
            for row in s.run(
                """
                MATCH (a:Application)-[:CALLS]->(e:Endpoint {host:$host})
                WHERE a.name <> $host
                RETURN DISTINCT a.name AS name ORDER BY name
                """,
                host=host_app,
            )
        ]


def consumers_of_topic(driver: Driver, topic: str) -> list[str]:
    with driver.session() as s:
        return [
            row["name"]
            for row in s.run(
                "MATCH (a:Application)-[:CONSUMES]->(:Topic {name:$t}) RETURN DISTINCT a.name AS name ORDER BY name",
                t=topic,
            )
        ]


def readers_of_table(driver: Driver, fqn: str) -> list[str]:
    with driver.session() as s:
        return [
            row["name"]
            for row in s.run(
                """
                MATCH (a:Application)-[:READS_TABLE]->(:DBTable {fqn:$fqn})
                RETURN DISTINCT a.name AS name ORDER BY name
                """,
                fqn=fqn,
            )
        ]


def readers_of_schema(driver: Driver, schema: str) -> list[str]:
    with driver.session() as s:
        return [
            row["name"]
            for row in s.run(
                """
                MATCH (a:Application)-[:READS_TABLE]->(t:DBTable {schema:$schema})
                RETURN DISTINCT a.name AS name ORDER BY name
                """,
                schema=schema,
            )
        ]


def readers_of_file(driver: Driver, path: str) -> list[str]:
    with driver.session() as s:
        return [
            row["name"]
            for row in s.run(
                """
                MATCH (a:Application)-[:READS_FILE]->(:FileFeed {path:$path})
                RETURN DISTINCT a.name AS name ORDER BY name
                """,
                path=path,
            )
        ]


def dependents_of_library(driver: Driver, gav: str) -> list[str]:
    with driver.session() as s:
        return [
            row["name"]
            for row in s.run(
                """
                MATCH (a:Application)-[:DEPENDS_ON_LIB]->(:Library {gav:$gav})
                RETURN DISTINCT a.name AS name ORDER BY name
                """,
                gav=gav,
            )
        ]
