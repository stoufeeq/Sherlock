"""Tree-sitter-driven Python extractor for HTTP client patterns the regex misses.

Targets the httpx / requests idioms our fixtures use:

  await self._client.get("/accounts/{id}")              # already caught by regex
  await self._client.get(f"/accounts/{aid}/balance")    # already caught
  url = f"/v2/accounts/{aid}/status"
  await self._client.get(url)                           # MISSED by regex (variable-resolved)

  PATH = "/accounts/" + str(aid) + "/balance"
  client.get(PATH)                                       # MISSED (string-concat)

Strategy:
  1. Parse the file with tree-sitter Python grammar.
  2. Build a per-file `name → string-literal` table from `NAME = "..."` /
     `NAME = f"..."` assignments (top-level + function-local).
  3. Walk every `call` node where the callee's attribute is one of HTTP_METHODS.
  4. For each call, look at the first positional arg:
       · string literal / f-string → use the literal text (best-effort interpolation).
       · identifier in our name table → resolve.
       · otherwise → skip.
  5. Pair each resolved path with the most-recently-seen `http://host` literal
     in the same file (same heuristic as code_refs).

Falls back gracefully (returns []) if the language pack is unavailable.
"""

from __future__ import annotations

import logging
import re

log = logging.getLogger("sherlock.analyzer.treesitter_python")

_PARSER = None
_AVAILABLE: bool | None = None

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "request"}


def _normalize_path(raw: str) -> str:
    raw = raw.split("?", 1)[0]
    raw = re.sub(r"\$\{[^}]+\}", "{*}", raw)
    raw = re.sub(r"\{[^}]+\}", "{*}", raw)
    return raw


def _ensure_parser():
    global _PARSER, _AVAILABLE
    if _AVAILABLE is False:
        return None
    if _PARSER is not None:
        return _PARSER
    try:
        from tree_sitter_language_pack import get_parser
        _PARSER = get_parser("python")
        _AVAILABLE = True
        return _PARSER
    except Exception as exc:
        log.warning("tree-sitter Python unavailable, falling back to regex only: %s", exc)
        _AVAILABLE = False
        return None


def _text(node, src: bytes) -> str:
    return src[node.start_byte:node.end_byte].decode("utf-8", errors="ignore")


def _string_value(node, src: bytes) -> str | None:
    """Return the contents of a `string` node (handles plain & f-strings).

    For f-strings, interpolations are replaced with `{*}` so the result is a
    template the path normalizer can clean up further.
    """
    if node.type != "string":
        return None
    raw = _text(node, src)
    # Strip Python string prefix flags + quotes
    m = re.match(r'^([rRbBfFuU]{0,2})(["\']{1,3})(.*)\2$', raw, re.DOTALL)
    if not m:
        return None
    body = m.group(3)
    # f-strings: collapse interpolations to {*}
    if "f" in m.group(1).lower():
        body = re.sub(r"\{[^{}]+\}", "{*}", body)
    return body


def _walk(root):
    stack = [root]
    while stack:
        n = stack.pop()
        yield n
        for c in n.children:
            stack.append(c)


def _build_string_var_table(root, src: bytes) -> dict[str, str]:
    """Find module/function-level `NAME = "..."` (or f"...") assignments and map them.

    Only considers single-target assignments — keeps the implementation tractable.
    """
    table: dict[str, str] = {}
    for n in _walk(root):
        if n.type != "assignment":
            continue
        # An `assignment` node has children: target, "=", value
        if len(n.children) < 3:
            continue
        target = n.children[0]
        value = n.children[-1]
        if target.type != "identifier":
            continue
        sv = _string_value(value, src)
        if sv is not None:
            table[_text(target, src)] = sv
    return table


_URL_RE = re.compile(r"https?://([A-Za-z0-9][A-Za-z0-9.\-]+)")
_SKIP_HOSTS = {"localhost", "127.0.0.1", "example.com", "kafka", "redpanda"}
_APP_HOST_RE = re.compile(r"^[a-z0-9][a-z0-9\-]+$")


def extract_calls(text: str) -> list[tuple[str | None, str, str]]:
    parser = _ensure_parser()
    if parser is None:
        return []

    src = text.encode("utf-8")
    try:
        tree = parser.parse(src)
    except Exception:
        log.exception("tree-sitter Python parse failed")
        return []

    host_offsets: list[tuple[int, str]] = []
    for m in _URL_RE.finditer(text):
        host = m.group(1)
        if host in _SKIP_HOSTS or not _APP_HOST_RE.match(host):
            continue
        host_offsets.append((m.start(), host))

    def host_for(offset: int) -> str | None:
        best = None
        for start, h in host_offsets:
            if start <= offset:
                best = h
            else:
                break
        return best

    var_table = _build_string_var_table(tree.root_node, src)
    out: list[tuple[str | None, str, str]] = []

    for n in _walk(tree.root_node):
        if n.type != "call":
            continue
        callee = n.child_by_field_name("function")
        args = n.child_by_field_name("arguments")
        if callee is None or args is None or callee.type != "attribute":
            continue
        attr = callee.child_by_field_name("attribute")
        if attr is None:
            continue
        method = _text(attr, src).lower()
        if method not in HTTP_METHODS:
            continue
        # First positional argument
        first = None
        for c in args.children:
            if c.type in ("(", ")", ","):
                continue
            if c.type == "keyword_argument":
                continue
            first = c
            break
        if first is None:
            continue
        path: str | None = None
        if first.type == "string":
            path = _string_value(first, src)
        elif first.type == "identifier":
            path = var_table.get(_text(first, src))
        if not path or not path.startswith("/"):
            continue
        verb = method.upper() if method != "request" else "GET"
        out.append((host_for(n.start_byte), verb, _normalize_path(path)))
    return out
