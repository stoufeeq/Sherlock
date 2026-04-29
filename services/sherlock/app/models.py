from dataclasses import dataclass, field
from typing import Literal

EdgeType = Literal[
    "EXPOSES",
    "CALLS",
    "PUBLISHES",
    "CONSUMES",
    "DEPENDS_ON_LIB",
    "PUBLISHES_LIB",
    "OWNS_SCHEMA",
    "READS_TABLE",
    "WRITES_TABLE",
    "CONTAINS_TABLE",
    "READS_FILE",
    "WRITES_FILE",
]


@dataclass
class AnalysisResult:
    """Everything one repo scan produced — the orchestrator turns this into graph upserts."""

    app_name: str
    commit_sha: str
    # Outbound edges from the Application node, plus a few helpers
    exposed_endpoints: list[tuple[str, str]] = field(default_factory=list)      # (method, path)
    called_endpoints: list[tuple[str, str, str]] = field(default_factory=list)  # (target_host, method, path_prefix)
    published_topics: list[str] = field(default_factory=list)
    consumed_topics: list[str] = field(default_factory=list)
    library_deps: list[str] = field(default_factory=list)                       # ["group:artifact"]
    library_published: str | None = None                                         # "group:artifact" if this repo publishes a lib
    owned_schemas: list[str] = field(default_factory=list)
    created_tables: list[str] = field(default_factory=list)                     # ["schema.table"]
    read_tables: list[str] = field(default_factory=list)
    written_tables: list[str] = field(default_factory=list)
    # Host-name hints seen in code, for later resolution to app ids
    seen_hosts: list[str] = field(default_factory=list)
    # (method, path) -> (request_full_hash, response_full_hash) — full schema fingerprint
    endpoint_shapes: dict[tuple[str, str], tuple[str | None, str | None]] = field(default_factory=dict)
    # (method, path) -> (request_required_hash, response_required_hash) — required-fields-only fingerprint.
    # Lets the diff engine separate breaking schema changes (required field removed/changed) from
    # additive ones (new optional field) — eliminates a major source of false-positive impact alerts.
    endpoint_required_shapes: dict[tuple[str, str], tuple[str | None, str | None]] = field(default_factory=dict)
    # (method, path) of endpoints flagged with `deprecated: true` in OpenAPI. When such an
    # endpoint is REMOVED, the diff engine downgrades severity (the team announced their intent).
    deprecated_endpoints: set[tuple[str, str]] = field(default_factory=set)
    # topic -> payload_hash — full payload fingerprint for shape changes
    topic_shapes: dict[str, str] = field(default_factory=dict)
    # topic -> payload_required_hash — required-fields-only fingerprint, mirrors
    # endpoint_required_shapes. Lets the diff engine separate breaking topic-payload
    # changes from purely additive ones (new optional field on the event).
    topic_required_shapes: dict[str, str] = field(default_factory=dict)
    # Shared-filesystem feed paths this app reads or writes (e.g. "/shared/postings/POSTINGS.DAT")
    read_files: list[str] = field(default_factory=list)
    written_files: list[str] = field(default_factory=list)
    # Gateway-resolved CALLS provenance — keyed on the BACKEND triple
    # (target_app, method, backend_path) after rewrite. Value is the gateway name.
    # Lets the graph writer stamp `via_gateway` on the CALLS edge so the canvas
    # can show "via apigee" instead of pretending the call was direct.
    gateway_resolved: dict[tuple[str, str, str], str] = field(default_factory=dict)
