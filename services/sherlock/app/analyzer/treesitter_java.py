"""Tree-sitter-driven Java extractor for HTTP client call patterns the regex misses.

Targets Spring's `RestClient` / `WebClient` idioms:

  http.get().uri("/v1/accounts/{id}", id).retrieve()                       # already caught by regex
  http.get().uri(b -> b.path("/accounts/{id}/balance").build(id)).retrieve()   # MISSED by regex
  http.method(HttpMethod.GET).uri("/x").retrieve()                          # MISSED
  String url = "/v2/accounts/{id}"; http.get().uri(url).retrieve()          # variable-resolved (best-effort)

Strategy:
  1. Parse the file with tree-sitter Java grammar.
  2. Walk for `method_invocation` nodes named `uri`.
  3. For each match, look at the argument list:
       - first arg is a string_literal → take the literal
       - first arg is a lambda → walk its body for `.path("...")` calls
       - first arg is an identifier → resolve via a tiny per-file `String NAME = "..."` map
  4. For each captured path, look UP the call chain for a sibling `.METHOD()` (get/post/...)
     to determine the HTTP verb. Default to GET when ambiguous.
  5. Find the host by walking up to the nearest enclosing `RestClient.builder().baseUrl(...)`
     literal — same heuristic as the regex extractor.

Returns the same triples as code_refs (`(host, method, normalized_path)`) so the orchestrator
can merge results without changes.

Falls back gracefully (returns []) if tree-sitter or its language pack is unavailable.
"""

from __future__ import annotations

import logging
import re

log = logging.getLogger("sherlock.analyzer.treesitter_java")

_PARSER = None
_AVAILABLE: bool | None = None  # tri-state: None=unchecked, True/False after first call


def _normalize_path(raw: str) -> str:
    """Match the same form code_refs.py + openapi.py use, so caller and exposer align."""
    raw = raw.split("?", 1)[0]
    raw = re.sub(r"\$\{[^}]+\}", "{*}", raw)
    raw = re.sub(r"\{[^}]+\}", "{*}", raw)
    return raw


def _ensure_parser():
    """Lazy-init the tree-sitter Java parser. Cache on success; remember failure on miss."""
    global _PARSER, _AVAILABLE
    if _AVAILABLE is False:
        return None
    if _PARSER is not None:
        return _PARSER
    try:
        from tree_sitter_language_pack import get_parser
        _PARSER = get_parser("java")
        _AVAILABLE = True
        return _PARSER
    except Exception as exc:
        log.warning("tree-sitter Java unavailable, falling back to regex only: %s", exc)
        _AVAILABLE = False
        return None


def _text(node, src: bytes) -> str:
    return src[node.start_byte:node.end_byte].decode("utf-8", errors="ignore")


def _string_literal_value(node, src: bytes) -> str | None:
    """Return the string contents of a `string_literal` node, or None if it's not one."""
    if node.type != "string_literal":
        return None
    raw = _text(node, src)
    # Java string literals: "..."
    if raw.startswith('"') and raw.endswith('"'):
        return raw[1:-1]
    return None


def _walk_method_invocations(root):
    """Yield every method_invocation node in the tree."""
    stack = [root]
    while stack:
        n = stack.pop()
        if n.type == "method_invocation":
            yield n
        for c in n.children:
            stack.append(c)


def _named_field(node, field):
    """Get a named child by tree-sitter field name."""
    return node.child_by_field_name(field)


def _build_string_var_table(root, src: bytes) -> dict[str, str]:
    """Find `String NAME = "..."` declarations so .uri(NAME) calls can be resolved."""
    table: dict[str, str] = {}
    stack = [root]
    while stack:
        n = stack.pop()
        if n.type == "local_variable_declaration":
            # children: type, variable_declarator(s)
            for c in n.children:
                if c.type == "variable_declarator":
                    name_node = _named_field(c, "name")
                    val_node = _named_field(c, "value")
                    if name_node and val_node:
                        if val_node.type == "string_literal":
                            sv = _string_literal_value(val_node, src)
                            if sv is not None:
                                table[_text(name_node, src)] = sv
        for c in n.children:
            stack.append(c)
    return table


def _extract_paths_from_uri_call(uri_call, src: bytes, var_table: dict[str, str]) -> list[str]:
    """Given a method_invocation node whose method is `uri`, return path string(s) found.

    Handles:
      .uri("literal", args...)
      .uri(varName)
      .uri(b -> b.path("literal").build(...))
      .uri(b -> b.path("literal").queryParam(...).build(...))
    """
    args = _named_field(uri_call, "arguments")
    if args is None:
        return []
    # arguments: argument_list  -> children include "(", expressions..., ")"
    paths: list[str] = []
    for arg in args.children:
        if arg.type in ("(", ")", ","):
            continue
        v = _string_literal_value(arg, src)
        if v is not None:
            paths.append(v)
            continue
        if arg.type == "identifier":
            ident = _text(arg, src)
            if ident in var_table:
                paths.append(var_table[ident])
            continue
        if arg.type == "lambda_expression":
            # Lambda body: walk for .path("...") calls
            for inner in _walk_method_invocations(arg):
                name_node = _named_field(inner, "name")
                if name_node is None:
                    continue
                if _text(name_node, src) != "path":
                    continue
                inner_args = _named_field(inner, "arguments")
                if inner_args is None:
                    continue
                for inner_arg in inner_args.children:
                    sv = _string_literal_value(inner_arg, src)
                    if sv is not None:
                        paths.append(sv)
    return paths


def _extract_method_for_uri(uri_call, src: bytes) -> str:
    """Walk up the call chain from a `.uri(...)` invocation to find the originating
    .get()/.post()/etc. so we can attribute an HTTP verb. Default GET if absent."""
    methods = {"get", "post", "put", "patch", "delete", "head", "options"}
    # Walk leftward through chained method_invocation parents
    cur = uri_call
    for _ in range(6):  # cap chain depth
        # The "object" field of a method_invocation is the receiver (i.e., what's to the left of ".")
        obj = _named_field(cur, "object")
        if obj is None:
            break
        if obj.type == "method_invocation":
            name_node = _named_field(obj, "name")
            if name_node is not None:
                name = _text(name_node, src)
                if name.lower() in methods:
                    return name.upper()
            cur = obj
            continue
        break
    return "GET"  # safe default — Spring's WebClient infers GET if method() not called


# Hosts: borrow the regex from code_refs to find http://host references in the same file.
_URL_RE = re.compile(r"https?://([A-Za-z0-9][A-Za-z0-9.\-]+)")
_SKIP_HOSTS = {"localhost", "127.0.0.1", "example.com", "kafka", "redpanda"}
_APP_HOST_RE = re.compile(r"^[a-z0-9][a-z0-9\-]+$")


def extract_calls(text: str) -> list[tuple[str | None, str, str]]:
    """Return list of (host_or_None, method, normalized_path) for every URI literal we find.

    Host resolution is best-effort: take the LAST http://host literal we see in the file
    before the call site. orchestrator pairs unresolved hosts via the existing fallback.
    """
    parser = _ensure_parser()
    if parser is None:
        return []

    src = text.encode("utf-8")
    try:
        tree = parser.parse(src)
    except Exception:
        log.exception("tree-sitter Java parse failed")
        return []

    # Pre-collect host offsets (same heuristic as code_refs)
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

    for inv in _walk_method_invocations(tree.root_node):
        name_node = _named_field(inv, "name")
        if name_node is None or _text(name_node, src) != "uri":
            continue
        for raw_path in _extract_paths_from_uri_call(inv, src, var_table):
            if not raw_path.startswith("/"):
                continue
            method = _extract_method_for_uri(inv, src)
            out.append((host_for(inv.start_byte), method, _normalize_path(raw_path)))
    return out
