"""Tree-sitter-driven JavaScript/TypeScript extractor for HTTP client patterns
the regex misses.

Targets the axios + native fetch idioms our fixtures use:

  await http.get(`/accounts/${id}`)                    # already caught by regex
  const url = `/v2/accounts/${id}/status`;
  await http.get(url)                                  # MISSED (variable-resolved template)
  await fetch('/path')                                 # mostly OK; tree-sitter is more robust
  axios({ method: 'get', url: '/transactions' })       # MISSED (object-form axios)

Strategy:
  1. Parse the file with tree-sitter JavaScript grammar (also covers most TS files
     well enough for our path-extraction needs).
  2. Build a per-file `name → string` table from `const NAME = "..."` /
     `let NAME = `template`` declarations.
  3. Walk every `call_expression`. Two shapes matter:
       a) callee is a member_expression where `.property` is one of HTTP_METHODS
          → the first arg is the URL (literal or identifier).
       b) callee identifier is `axios` / `fetch` / `request` and the first arg is
          a string literal (URL) OR an object_expression with a `url` property.
  4. Pair each resolved path with the most-recently-seen `http://host` literal
     in the same file (same heuristic as code_refs).

Falls back gracefully (returns []) if the language pack is unavailable.
"""

from __future__ import annotations

import logging
import re

log = logging.getLogger("sherlock.analyzer.treesitter_js")

_PARSER = None
_AVAILABLE: bool | None = None

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "request"}
TOP_LEVEL_HTTP_FNS = {"axios", "fetch", "request"}


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
        _PARSER = get_parser("javascript")
        _AVAILABLE = True
        return _PARSER
    except Exception as exc:
        log.warning("tree-sitter JavaScript unavailable, falling back to regex only: %s", exc)
        _AVAILABLE = False
        return None


def _text(node, src: bytes) -> str:
    return src[node.start_byte:node.end_byte].decode("utf-8", errors="ignore")


def _string_value(node, src: bytes) -> str | None:
    """Decode a `string` or `template_string` literal.

    For template strings, ${...} interpolations collapse to {*}.
    """
    if node.type == "string":
        # children: '"' / "'", string_fragment(s), '"' / "'"
        # Use raw and strip the outer quote
        raw = _text(node, src)
        if len(raw) >= 2 and raw[0] in ("'", '"') and raw[-1] == raw[0]:
            return raw[1:-1]
        return None
    if node.type == "template_string":
        raw = _text(node, src)
        if not (raw.startswith("`") and raw.endswith("`")):
            return None
        body = raw[1:-1]
        body = re.sub(r"\$\{[^{}]+\}", "{*}", body)
        return body
    return None


def _walk(root):
    stack = [root]
    while stack:
        n = stack.pop()
        yield n
        for c in n.children:
            stack.append(c)


def _build_string_var_table(root, src: bytes) -> dict[str, str]:
    """Map `const NAME = '...'` / `const NAME = \\`...\\`` / `let / var` to their literal."""
    table: dict[str, str] = {}
    for n in _walk(root):
        if n.type != "variable_declarator":
            continue
        name_node = n.child_by_field_name("name")
        value_node = n.child_by_field_name("value")
        if name_node is None or value_node is None:
            continue
        if name_node.type != "identifier":
            continue
        sv = _string_value(value_node, src)
        if sv is not None:
            table[_text(name_node, src)] = sv
    return table


def _first_positional(args_node, src: bytes):
    """Return the first non-comma child of an arguments node (or None)."""
    for c in args_node.children:
        if c.type in ("(", ")", ","):
            continue
        return c
    return None


def _extract_url_from_object_expr(obj_node, src: bytes,
                                  var_table: dict[str, str]) -> tuple[str | None, str | None]:
    """Look for `url:` and `method:` properties inside an object expression."""
    url, method = None, None
    for child in _walk(obj_node):
        if child.type != "pair":
            continue
        key = child.child_by_field_name("key")
        val = child.child_by_field_name("value")
        if key is None or val is None:
            continue
        key_name = _text(key, src).strip("'\"`")
        if key_name == "url":
            sv = _string_value(val, src)
            if sv is None and val.type == "identifier":
                sv = var_table.get(_text(val, src))
            if sv:
                url = sv
        elif key_name == "method":
            sv = _string_value(val, src)
            if sv:
                method = sv.upper()
    return url, method


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
        log.exception("tree-sitter JS parse failed")
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
        if n.type != "call_expression":
            continue
        callee = n.child_by_field_name("function")
        args = n.child_by_field_name("arguments")
        if callee is None or args is None:
            continue

        path: str | None = None
        verb: str | None = None

        if callee.type == "member_expression":
            prop = callee.child_by_field_name("property")
            if prop is None:
                continue
            method = _text(prop, src).lower()
            if method not in HTTP_METHODS:
                continue
            verb = method.upper() if method != "request" else "GET"
            first = _first_positional(args, src)
            if first is None:
                continue
            if first.type in ("string", "template_string"):
                path = _string_value(first, src)
            elif first.type == "identifier":
                path = var_table.get(_text(first, src))
            elif first.type == "object":
                # axios-like object inside .request({...})
                url, method_in_obj = _extract_url_from_object_expr(first, src, var_table)
                path = url
                if method_in_obj:
                    verb = method_in_obj
        elif callee.type == "identifier" and _text(callee, src) in TOP_LEVEL_HTTP_FNS:
            first = _first_positional(args, src)
            if first is None:
                continue
            if first.type in ("string", "template_string"):
                path = _string_value(first, src)
                verb = "GET"
            elif first.type == "identifier":
                path = var_table.get(_text(first, src))
                verb = "GET"
            elif first.type == "object":
                url, method_in_obj = _extract_url_from_object_expr(first, src, var_table)
                path = url
                verb = method_in_obj or "GET"

        if not path or not path.startswith("/") or not verb:
            continue
        out.append((host_for(n.start_byte), verb, _normalize_path(path)))
    return out
