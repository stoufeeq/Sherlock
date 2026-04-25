"""Extract publish/subscribe topics from AsyncAPI YAML.

For each PUBLISHED topic we record TWO payload fingerprints:
  · full_hash — fingerprint of the entire payload schema
  · required_hash — fingerprint of only the `required` subset

The diff engine treats:
  · required_hash differs → `topic_payload_changed`        (breaking — consumers may break)
  · only full_hash differs → `topic_payload_extended`      (info — additive new optional field)

Mirrors the same precision treatment we apply to OpenAPI request/response bodies.
"""

import hashlib
import json
from pathlib import Path

import yaml

from app.models import AnalysisResult


def _schema_hash(schema) -> str | None:
    if schema is None:
        return None
    blob = json.dumps(schema, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()[:12]


def _required_subset(schema) -> dict | None:
    """Return only the contractual subset of an event payload — `required` field
    list + the type signature of each required field. Optional-field changes
    leave the result unchanged."""
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
            field = properties.get(name)
            if isinstance(field, dict):
                # Carry only type-relevant keys, not descriptions/examples.
                # Recurse one level for nested object types so a required nested
                # field's required-subset is also captured.
                inner = {k: field[k] for k in ("type", "format", "enum") if k in field}
                if field.get("type") == "object":
                    inner["required_subset"] = _required_subset(field)
                out["properties"][name] = inner
            else:
                out["properties"][name] = None
    for combinator in ("oneOf", "anyOf", "allOf"):
        if combinator in schema and isinstance(schema[combinator], list):
            out[combinator] = [_required_subset(sub) for sub in schema[combinator]]
    return out


def _payload(op: dict):
    msg = op.get("message") or {}
    # AsyncAPI 2.x puts the schema under message.payload; 3.x moves it around.
    return msg.get("payload")


def parse_asyncapi(path: Path, result: AnalysisResult) -> None:
    with path.open() as f:
        spec = yaml.safe_load(f)
    if not isinstance(spec, dict):
        return
    for topic, ops in (spec.get("channels") or {}).items():
        if not isinstance(ops, dict):
            continue
        if "publish" in ops:
            result.published_topics.append(topic)
            payload = _payload(ops["publish"])
            full = _schema_hash(payload)
            req = _schema_hash(_required_subset(payload))
            if full:
                result.topic_shapes[topic] = full
            if req:
                result.topic_required_shapes[topic] = req
        if "subscribe" in ops:
            result.consumed_topics.append(topic)
