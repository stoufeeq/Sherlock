"""APIGEE-style gateway resolver.

Without this module, a caller doing
    GET https://api.ubs.com/banking/v1/accounts/{id}
ends up as a CALLS edge into a black-hole `api.ubs.com` node — the host doesn't
match any real Application, and every consumer of any API behind the gateway
would falsely fan out from that single node.

The resolver loads an APIGEE-bundle-shaped YAML once, and at scan time rewrites
gateway-host triples to backend-app triples, recording the gateway's name in
`AnalysisResult.gateway_resolved` so the graph writer can stamp `via_gateway`
on the resulting CALLS edge.

Match precedence is longest-basepath-first — `/banking/v1/accounts` beats
`/banking/v1` if both are configured.
"""

import logging
import os
from dataclasses import dataclass
from pathlib import Path

import yaml

from app.models import AnalysisResult

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Route:
    basepath: str          # e.g. "/banking/v1/accounts"
    target_app: str        # e.g. "account-service"
    target_basepath: str   # e.g. "/accounts"


@dataclass
class GatewayConfig:
    name: str
    hosts: tuple[str, ...]
    routes: tuple[_Route, ...]   # sorted longest-basepath-first


_CACHE: dict[str, list[GatewayConfig]] = {}


def _load(path: str) -> list[GatewayConfig]:
    if path in _CACHE:
        return _CACHE[path]
    p = Path(path)
    if not p.is_file():
        log.info("gateway config not found at %s — gateway resolution disabled", path)
        _CACHE[path] = []
        return _CACHE[path]
    try:
        raw = yaml.safe_load(p.read_text()) or {}
    except Exception as exc:
        log.warning("failed to parse gateway config %s: %s", path, exc)
        _CACHE[path] = []
        return _CACHE[path]

    out: list[GatewayConfig] = []
    for gw in raw.get("gateways", []):
        try:
            routes = sorted(
                (_Route(
                    basepath=str(r["basepath"]).rstrip("/"),
                    target_app=str(r["target_app"]),
                    target_basepath=str(r["target_basepath"]).rstrip("/"),
                 ) for r in gw.get("routes", []) or []),
                key=lambda r: -len(r.basepath),
            )
            out.append(GatewayConfig(
                name=str(gw["name"]),
                hosts=tuple(str(h) for h in gw.get("hosts", []) or []),
                routes=tuple(routes),
            ))
        except Exception as exc:
            log.warning("skipping malformed gateway entry: %s (%s)", gw, exc)
    log.info("loaded %s gateway(s) from %s", len(out), path)
    _CACHE[path] = out
    return out


def reset_cache() -> None:
    """Clear the in-process cache. Useful in tests; not used at runtime."""
    _CACHE.clear()


def _resolve_one(host: str, path: str, gateways: list[GatewayConfig]
                 ) -> tuple[str, str, str] | None:
    """Return (gateway_name, target_app, rewritten_path) or None if no gateway matches."""
    for gw in gateways:
        if host not in gw.hosts:
            continue
        for r in gw.routes:
            # exact-prefix match on basepath
            if path == r.basepath or path.startswith(r.basepath + "/"):
                tail = path[len(r.basepath):]   # includes leading "/" if any
                rewritten = r.target_basepath + tail
                if not rewritten.startswith("/"):
                    rewritten = "/" + rewritten
                return gw.name, r.target_app, rewritten
        # host matched but no route did — leave for the caller to decide; we
        # return None so the regular black-hole behaviour kicks in.
        return None
    return None


def resolve_in_place(result: AnalysisResult, *, config_path: str | None = None) -> int:
    """Rewrite gateway-host CALLS triples in `result` to point at the real backend.

    Returns the number of triples rewritten — useful for logging.
    Idempotent: if no gateways match, the result is unchanged.
    """
    path = config_path or os.getenv("SHERLOCK_GATEWAY_CONFIG", "/etc/sherlock/gateway-routes.yaml")
    gateways = _load(path)
    if not gateways:
        return 0

    rewritten_count = 0
    new_triples: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for host, method, p in result.called_endpoints:
        match = _resolve_one(host, p, gateways)
        if match is None:
            triple = (host, method, p)
            if triple not in seen:
                new_triples.append(triple)
                seen.add(triple)
            continue
        gw_name, target_app, new_path = match
        triple = (target_app, method, new_path)
        if triple not in seen:
            new_triples.append(triple)
            seen.add(triple)
        # Last-write-wins is fine: same triple from two sources is still via the same gateway.
        result.gateway_resolved[triple] = gw_name
        rewritten_count += 1

    result.called_endpoints = new_triples

    # Same idea for seen_hosts: replace gateway hosts with the backend apps they
    # resolve to, so app-level fallback edges land on the right node.
    new_hosts: list[str] = []
    seen_h: set[str] = set()
    gateway_hosts = {h for gw in gateways for h in gw.hosts}
    for h in result.seen_hosts:
        if h in gateway_hosts:
            continue   # raw gateway host is uninformative without a path
        if h not in seen_h:
            new_hosts.append(h)
            seen_h.add(h)
    # Add the backends we now know about.
    for (target_app, _m, _p) in result.gateway_resolved:
        if target_app not in seen_h:
            new_hosts.append(target_app)
            seen_h.add(target_app)
    result.seen_hosts = new_hosts

    return rewritten_count
