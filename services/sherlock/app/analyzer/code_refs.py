"""Extract outbound HTTP call sites with enough precision to know the target app
and the specific (method, path) being called.

Strategy:
  1. For every source file, scan for full http(s)://host[:port] URLs. Those let us
     seed a pool of candidate base URLs and mark apps as seen_hosts.
  2. Then, per language, look for client method calls ( .get("/x"), .post(...), etc. )
     and pair them with the most recently-seen base URL in the same file to produce
     concrete (host, method, path) triples.

Regex-only — trees/ASTs deferred. Good enough for the fixture idioms we wrote
(Spring RestClient, httpx, axios).
"""

import re
from pathlib import Path

from app.models import AnalysisResult

# ---- generic URL extractor ---------------------------------------------------
# Matches URLs like http://account-service:8080
URL_RE = re.compile(
    r"https?://([A-Za-z0-9][A-Za-z0-9.\-]+)(?::(\d+))?",
)
SKIP_HOSTS = {"localhost", "127.0.0.1", "example.com", "kafka", "redpanda"}

# Token that the URL must "belong to" an app name — hyphenated, lowercase
APP_HOST_RE = re.compile(r"^[a-z0-9][a-z0-9\-]+$")

HTTP_METHODS = ("get", "post", "put", "patch", "delete", "head", "options")

# ---- per-language client call patterns ---------------------------------------
# Each pattern captures (method, path). Limited to same-file scope; we pair each
# match with the most recently-seen base URL host in the same file.

# Java (Spring RestClient / RestTemplate / WebClient):
#   http.get().uri("/accounts/{id}", ...)    http.post().uri("/x")   http.uri("/...")
JAVA_CALL_RE = re.compile(
    r"\.(get|post|put|patch|delete|head|options)\s*\(\s*\)\s*\.uri\s*\(\s*\"([^\"]+)\"",
    re.IGNORECASE,
)
# Fallback: http.uri("/x") when method is elided
JAVA_URI_ONLY_RE = re.compile(r"\.uri\s*\(\s*\"([^\"]+)\"")

# Python httpx / requests:
#   await self._client.get(f"/accounts/{account_id}")
#   client.post("/transactions", json=...)
PY_CALL_RE = re.compile(
    r"\.(get|post|put|patch|delete|head|options)\s*\(\s*[rfb]?[\"']([^\"']+)[\"']",
    re.IGNORECASE,
)

# JavaScript / TypeScript axios:
#   http.get(`/accounts/${id}`)    http.post('/transactions', body)
JS_CALL_RE = re.compile(
    r"\.(get|post|put|patch|delete|head|options)\s*\(\s*[`'\"]([^`'\"]+)[`'\"]",
    re.IGNORECASE,
)


def _normalize_path(raw: str) -> str:
    """Turn a raw path literal into a stable pattern that matches the OpenAPI form.

    `/accounts/${id}`          -> /accounts/{*}
    `/accounts/{account_id}`   -> /accounts/{*}
    `/accounts/{id}/balance`   -> /accounts/{*}/balance

    Matching uses `{*}` for every path parameter so callers and exposers align
    regardless of the variable name they picked.
    """
    path = raw.split("?", 1)[0]
    path = re.sub(r"\$\{[^}]+\}", "{*}", path)           # JS template literal
    path = re.sub(r"\{[^}]+\}", "{*}", path)             # {id}, {account_id}, {x:.2f} → {*}
    return path


def _ext(path: Path) -> str:
    return path.suffix.lower()


def _parse_hosts(text: str) -> list[tuple[int, str]]:
    """Return (offset, host) pairs for every http(s) URL match."""
    out = []
    for m in URL_RE.finditer(text):
        host = m.group(1)
        if host in SKIP_HOSTS or not APP_HOST_RE.match(host):
            continue
        out.append((m.start(), host))
    return out


def _host_for(offset: int, host_offsets: list[tuple[int, str]]) -> str | None:
    """Find the closest host whose URL appears on-or-before `offset`."""
    best: str | None = None
    for start, host in host_offsets:
        if start <= offset:
            best = host
        else:
            break
    return best


def _extract_calls_for_language(text: str, ext: str) -> list[tuple[int, str, str]]:
    """Return a list of (offset, method, path) for HTTP client calls in this file."""
    calls: list[tuple[int, str, str]] = []
    if ext == ".java":
        for m in JAVA_CALL_RE.finditer(text):
            calls.append((m.start(), m.group(1).upper(), _normalize_path(m.group(2))))
        # .uri("/x") without a preceding .get()/.post() — record with method=GET as default
        for m in JAVA_URI_ONLY_RE.finditer(text):
            # avoid duplicates with JAVA_CALL_RE hits
            already = any(abs(c[0] - m.start()) < 30 for c in calls)
            if not already:
                calls.append((m.start(), "GET", _normalize_path(m.group(1))))
    elif ext == ".py":
        for m in PY_CALL_RE.finditer(text):
            method = m.group(1).upper()
            path = _normalize_path(m.group(2))
            if not path.startswith("/"):
                continue
            calls.append((m.start(), method, path))
    elif ext in {".js", ".mjs", ".ts"}:
        for m in JS_CALL_RE.finditer(text):
            method = m.group(1).upper()
            path = _normalize_path(m.group(2))
            if not path.startswith("/"):
                continue
            calls.append((m.start(), method, path))
    return calls


def scan_for_outbound_hosts(path: Path, result: AnalysisResult) -> None:
    text = path.read_text(errors="ignore")
    hosts = _parse_hosts(text)

    # Record every distinct host we see, even without a paired call — keeps app-level
    # impact working as a fallback.
    for _off, host in hosts:
        if host not in result.seen_hosts:
            result.seen_hosts.append(host)

    ext = _ext(path)
    calls = _extract_calls_for_language(text, ext)

    # For config files (yaml / properties), we typically only have baseURL references
    # and no literal path calls — fall back to a catch-all so the BFF→app CALLS edge
    # still exists.
    if not calls and hosts and ext in {".yml", ".yaml", ".properties", ".xml"}:
        for _off, host in hosts:
            triple = (host, "*", "/*")
            if triple not in result.called_endpoints:
                result.called_endpoints.append(triple)
        return

    for offset, method, call_path in calls:
        host = _host_for(offset, hosts)
        if not host:
            continue
        triple = (host, method, call_path)
        if triple not in result.called_endpoints:
            result.called_endpoints.append(triple)
