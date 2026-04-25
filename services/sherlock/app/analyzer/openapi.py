"""Extract exposed REST endpoints from OpenAPI YAML.

Per endpoint we capture:
  · normalized (method, path) — `{id}` / `{accountId}` / `${id}` all become `{*}`
  · full schema fingerprint — for fine-grained change detection
  · required-fields fingerprint — only the breaking subset of the schema
  · `deprecated: true` flag — so the diff engine can downgrade severity when a
    previously-deprecated endpoint is finally removed
"""

import hashlib
import json
import re
from pathlib import Path

import yaml

from app.models import AnalysisResult

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}


def _normalize_path(raw: str) -> str:
    """Same normalization as code_refs: {id} / {account_id} / {userId} → {*}."""
    return re.sub(r"\{[^}]+\}", "{*}", raw.split("?", 1)[0])


def _schema_hash(schema) -> str | None:
    """Stable short hash over a JSON schema used to detect shape changes."""
    if schema is None:
        return None
    blob = json.dumps(schema, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()[:12]


def _resolve(spec: dict, node):
    """Inline a single $ref pointer — shallow dereference, one level deep."""
    if isinstance(node, dict) and "$ref" in node and isinstance(node["$ref"], str):
        ref = node["$ref"]
        if ref.startswith("#/"):
            cur = spec
            for part in ref[2:].split("/"):
                if isinstance(cur, dict) and part in cur:
                    cur = cur[part]
                else:
                    return node  # leave unresolved
            return cur
    return node


def _required_subset(spec: dict, schema) -> dict | None:
    """Return only the parts of `schema` that consumers can rely on contractually:
    the `required` field list itself, plus the type signatures of those required
    fields (recursing one level into nested objects).

    A change to OPTIONAL fields will leave the result of this function unchanged
    — that's the whole point. The diff engine treats a change here as breaking;
    a change in `_schema_hash(full)` but NOT here as additive (info-level).
    """
    schema = _resolve(spec, schema)
    if not isinstance(schema, dict):
        return None

    out: dict = {"type": schema.get("type")}
    required = schema.get("required") or []
    if isinstance(required, list):
        out["required"] = sorted(required)
    properties = schema.get("properties") or {}
    if isinstance(properties, dict) and required:
        out["properties"] = {}
        for name in sorted(required):
            field = _resolve(spec, properties.get(name))
            if isinstance(field, dict):
                # carry only the type contract (not descriptions / examples / etc.)
                out["properties"][name] = {
                    k: field[k] for k in ("type", "format", "enum", "items", "$ref")
                    if k in field
                }
            else:
                out["properties"][name] = None

    # Composition keywords: if the schema uses oneOf/anyOf/allOf, factor those in too
    for combinator in ("oneOf", "anyOf", "allOf"):
        if combinator in schema and isinstance(schema[combinator], list):
            out[combinator] = [_required_subset(spec, sub) for sub in schema[combinator]]
    return out


def _body_for(op: dict, which: str) -> dict | None:
    """Return the JSON body schema for `which` ∈ {'request','response'}, or None."""
    if which == "request":
        body = op.get("requestBody") or {}
    else:
        responses = op.get("responses") or {}
        body = responses.get("200") or responses.get("201") or responses.get("default") or {}
    content = (body.get("content") or {}).get("application/json") or {}
    return content.get("schema")


def parse_openapi(path: Path, result: AnalysisResult) -> None:
    with path.open() as f:
        spec = yaml.safe_load(f)
    if not isinstance(spec, dict):
        return
    for route, methods in (spec.get("paths") or {}).items():
        if not isinstance(methods, dict):
            continue
        route_norm = _normalize_path(route)
        for method, op in methods.items():
            if method.lower() not in HTTP_METHODS:
                continue
            if not isinstance(op, dict):
                continue
            method_upper = method.upper()
            key = (method_upper, route_norm)
            result.exposed_endpoints.append(key)

            req_schema = _body_for(op, "request")
            res_schema = _body_for(op, "response")

            req_full = _schema_hash(_resolve(spec, req_schema))
            res_full = _schema_hash(_resolve(spec, res_schema))
            req_req = _schema_hash(_required_subset(spec, req_schema))
            res_req = _schema_hash(_required_subset(spec, res_schema))

            if req_full or res_full:
                result.endpoint_shapes[key] = (req_full, res_full)
            if req_req or res_req:
                result.endpoint_required_shapes[key] = (req_req, res_req)

            if op.get("deprecated") is True:
                result.deprecated_endpoints.add(key)
