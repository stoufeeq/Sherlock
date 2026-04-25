from contextlib import contextmanager

from neo4j import GraphDatabase

from app.config import settings
from app.models import AnalysisResult


def _ext_of(path: str) -> str:
    if "." not in path.rsplit("/", 1)[-1]:
        return ""
    return path.rsplit(".", 1)[-1].upper()

CONSTRAINTS = [
    "CREATE CONSTRAINT application_name IF NOT EXISTS FOR (a:Application) REQUIRE a.name IS UNIQUE",
    "CREATE CONSTRAINT endpoint_id IF NOT EXISTS FOR (e:Endpoint) REQUIRE e.id IS UNIQUE",
    "CREATE CONSTRAINT topic_name IF NOT EXISTS FOR (t:Topic) REQUIRE t.name IS UNIQUE",
    "CREATE CONSTRAINT library_gav IF NOT EXISTS FOR (l:Library) REQUIRE l.gav IS UNIQUE",
    "CREATE CONSTRAINT schema_name IF NOT EXISTS FOR (s:DBSchema) REQUIRE s.name IS UNIQUE",
    "CREATE CONSTRAINT table_fqn IF NOT EXISTS FOR (t:DBTable) REQUIRE t.fqn IS UNIQUE",
    "CREATE CONSTRAINT filefeed_path IF NOT EXISTS FOR (f:FileFeed) REQUIRE f.path IS UNIQUE",
]


class GraphClient:
    def __init__(self) -> None:
        self._driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )

    def close(self) -> None:
        self._driver.close()

    @property
    def driver(self):
        return self._driver

    @contextmanager
    def _session(self):
        with self._driver.session() as s:
            yield s

    def ensure_schema(self) -> None:
        with self._session() as s:
            for stmt in CONSTRAINTS:
                s.run(stmt)

    def upsert_application(
        self,
        name: str,
        repo_url: str,
        team: str | None,
        tier: int | None,
        runtime: str | None,
        project_id: int | None = None,
    ) -> None:
        """Create-or-update an Application. Also clears any stale archived/rename markers
        (so an app that comes back from archival is automatically un-archived)."""
        with self._session() as s:
            s.run(
                """
                MERGE (a:Application {name: $name})
                SET a.repo_url = $repo_url,
                    a.team = $team,
                    a.tier = $tier,
                    a.runtime = $runtime,
                    a.project_id = coalesce($project_id, a.project_id),
                    a.archived = false
                REMOVE a.renamed_to, a.archived_at
                """,
                name=name,
                repo_url=repo_url,
                team=team,
                tier=tier,
                runtime=runtime,
                project_id=project_id,
            )

    def list_applications(self) -> list[dict]:
        """Return {name, project_id, archived} for every Application node."""
        with self._session() as s:
            return [
                {"name": r["name"], "project_id": r["pid"], "archived": bool(r["archived"])}
                for r in s.run(
                    "MATCH (a:Application) "
                    "RETURN a.name AS name, a.project_id AS pid, a.archived AS archived "
                    "ORDER BY name"
                )
            ]

    def find_name_by_project_id(self, project_id: int) -> str | None:
        with self._session() as s:
            row = s.run(
                "MATCH (a:Application {project_id:$pid}) RETURN a.name AS name LIMIT 1",
                pid=project_id,
            ).single()
            return row["name"] if row else None

    def mark_archived(self, name: str, *, renamed_to: str | None = None) -> None:
        """Flag an Application as archived. Preserves the node + its edges for history;
        callers (APIs, UI) decide whether to hide archived items by default."""
        with self._session() as s:
            s.run(
                """
                MATCH (a:Application {name:$name})
                SET a.archived = true,
                    a.archived_at = datetime(),
                    a.renamed_to = $renamed_to
                """,
                name=name,
                renamed_to=renamed_to,
            )

    def apply_analysis(self, result: AnalysisResult, host_to_app: dict[str, str]) -> None:
        """Replace all outgoing edges sourced by this app, then insert the new ones.

        `host_to_app` maps hostnames seen in code (e.g., "account-service") to
        application names — used to resolve CALLS edges.
        """
        with self._session() as s:
            s.execute_write(self._apply_analysis_tx, result, host_to_app)

    @staticmethod
    def _apply_analysis_tx(tx, result: AnalysisResult, host_to_app: dict[str, str]) -> None:
        app = result.app_name

        # Set commit SHA on the app
        tx.run("MATCH (a:Application {name:$app}) SET a.commit_sha=$sha", app=app, sha=result.commit_sha)

        # Wipe outgoing source-owned edges for idempotent re-scan
        tx.run(
            """
            MATCH (a:Application {name:$app})-[r]->()
            WHERE type(r) IN [
              'EXPOSES','CALLS','PUBLISHES','CONSUMES',
              'DEPENDS_ON_LIB','PUBLISHES_LIB',
              'OWNS_SCHEMA','READS_TABLE','WRITES_TABLE',
              'READS_FILE','WRITES_FILE'
            ]
            DELETE r
            """,
            app=app,
        )

        # Exposed endpoints — full + required-only shape hashes, plus deprecation flag.
        for method, path in result.exposed_endpoints:
            eid = f"{app}:{method}:{path}"
            req_hash, res_hash = result.endpoint_shapes.get((method, path), (None, None))
            req_req, res_req = result.endpoint_required_shapes.get((method, path), (None, None))
            is_deprecated = (method, path) in result.deprecated_endpoints
            tx.run(
                """
                MERGE (e:Endpoint {id:$id})
                  ON CREATE SET e.method=$method, e.path=$path, e.host=$app
                SET e.req_hash       = $req,
                    e.res_hash       = $res,
                    e.req_req_hash   = $req_required,
                    e.res_req_hash   = $res_required,
                    e.deprecated     = $deprecated
                WITH e
                MATCH (a:Application {name:$app})
                MERGE (a)-[:EXPOSES]->(e)
                """,
                id=eid,
                method=method,
                path=path,
                app=app,
                req=req_hash,
                res=res_hash,
                req_required=req_req,
                res_required=res_req,
                deprecated=is_deprecated,
            )

        # Called endpoints (resolve host to app → endpoint node)
        for host, method, path in result.called_endpoints:
            target_app = host_to_app.get(host)
            if not target_app:
                continue
            eid = f"{target_app}:{method}:{path}"
            tx.run(
                """
                MERGE (e:Endpoint {id:$id})
                  ON CREATE SET e.method=$method, e.path=$path, e.host=$target
                WITH e
                MATCH (a:Application {name:$app})
                MERGE (a)-[:CALLS]->(e)
                """,
                id=eid,
                method=method,
                path=path,
                target=target_app,
                app=app,
            )

        # Published / consumed topics — full + required-only payload hashes
        for topic in result.published_topics:
            payload_hash = result.topic_shapes.get(topic)
            payload_required = result.topic_required_shapes.get(topic)
            tx.run(
                """
                MERGE (t:Topic {name:$topic})
                SET t.payload_hash      = coalesce($hash, t.payload_hash),
                    t.payload_req_hash  = coalesce($req,  t.payload_req_hash)
                WITH t
                MATCH (a:Application {name:$app})
                MERGE (a)-[:PUBLISHES]->(t)
                """,
                topic=topic,
                hash=payload_hash,
                req=payload_required,
                app=app,
            )
        for topic in result.consumed_topics:
            tx.run(
                """
                MERGE (t:Topic {name:$topic})
                WITH t
                MATCH (a:Application {name:$app})
                MERGE (a)-[:CONSUMES]->(t)
                """,
                topic=topic,
                app=app,
            )

        # Library published by this repo
        if result.library_published:
            tx.run(
                """
                MERGE (l:Library {gav:$gav})
                WITH l
                MATCH (a:Application {name:$app})
                MERGE (a)-[:PUBLISHES_LIB]->(l)
                """,
                gav=result.library_published,
                app=app,
            )

        # Library dependencies
        for gav in result.library_deps:
            tx.run(
                """
                MERGE (l:Library {gav:$gav})
                WITH l
                MATCH (a:Application {name:$app})
                MERGE (a)-[:DEPENDS_ON_LIB]->(l)
                """,
                gav=gav,
                app=app,
            )

        # Schemas owned
        for schema in result.owned_schemas:
            tx.run(
                """
                MERGE (s:DBSchema {name:$schema})
                WITH s
                MATCH (a:Application {name:$app})
                MERGE (a)-[:OWNS_SCHEMA]->(s)
                """,
                schema=schema,
                app=app,
            )

        # Tables created by this app's migrations
        for fqn in result.created_tables:
            schema_name, table_name = fqn.split(".", 1)
            tx.run(
                """
                MERGE (s:DBSchema {name:$schema})
                MERGE (t:DBTable {fqn:$fqn})
                  ON CREATE SET t.name=$table, t.schema=$schema
                MERGE (s)-[:CONTAINS_TABLE]->(t)
                """,
                schema=schema_name,
                table=table_name,
                fqn=fqn,
            )

        # Read / written tables
        for fqn in result.read_tables:
            schema_name, table_name = fqn.split(".", 1)
            tx.run(
                """
                MERGE (s:DBSchema {name:$schema})
                MERGE (t:DBTable {fqn:$fqn})
                  ON CREATE SET t.name=$table, t.schema=$schema
                MERGE (s)-[:CONTAINS_TABLE]->(t)
                WITH t
                MATCH (a:Application {name:$app})
                MERGE (a)-[:READS_TABLE]->(t)
                """,
                schema=schema_name,
                table=table_name,
                fqn=fqn,
                app=app,
            )
        for fqn in result.written_tables:
            schema_name, table_name = fqn.split(".", 1)
            tx.run(
                """
                MERGE (s:DBSchema {name:$schema})
                MERGE (t:DBTable {fqn:$fqn})
                  ON CREATE SET t.name=$table, t.schema=$schema
                MERGE (s)-[:CONTAINS_TABLE]->(t)
                WITH t
                MATCH (a:Application {name:$app})
                MERGE (a)-[:WRITES_TABLE]->(t)
                """,
                schema=schema_name,
                table=table_name,
                fqn=fqn,
                app=app,
            )

        # Shared-filesystem feed coupling
        for feed_path in result.read_files:
            tx.run(
                """
                MERGE (f:FileFeed {path:$path})
                  ON CREATE SET f.name=$path, f.extension=$ext
                WITH f
                MATCH (a:Application {name:$app})
                MERGE (a)-[:READS_FILE]->(f)
                """,
                path=feed_path,
                ext=_ext_of(feed_path),
                app=app,
            )
        for feed_path in result.written_files:
            tx.run(
                """
                MERGE (f:FileFeed {path:$path})
                  ON CREATE SET f.name=$path, f.extension=$ext
                WITH f
                MATCH (a:Application {name:$app})
                MERGE (a)-[:WRITES_FILE]->(f)
                """,
                path=feed_path,
                ext=_ext_of(feed_path),
                app=app,
            )
