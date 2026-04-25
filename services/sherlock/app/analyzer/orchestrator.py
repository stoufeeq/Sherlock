"""Scan a single repo: clone → walk files → dispatch to parsers → return AnalysisResult."""

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.analyzer import (
    asyncapi, code_refs, files, manifests, openapi, sql,
    treesitter_java, treesitter_python, treesitter_js,
)
from app.models import AnalysisResult

log = logging.getLogger(__name__)

# Directories that aren't worth scanning
SKIP_DIRS = {".git", "target", "build", "node_modules", "__pycache__", ".venv", ".idea", ".vscode"}

# File types we scan for outbound HTTP hostnames and embedded SQL
CODE_EXTS = {".java", ".py", ".js", ".mjs", ".ts", ".cbl", ".cob", ".yml", ".yaml", ".properties", ".xml"}
CONFIG_EXTS = {".yml", ".yaml", ".properties"}


def _clone(clone_url: str, ref: str, dest: Path) -> None:
    subprocess.run(
        ["git", "clone", "--depth", "1", "--branch", ref, clone_url, str(dest)],
        check=True,
        capture_output=True,
    )


def scan_repo(*, app_name: str, clone_url: str, ref: str = "main") -> AnalysisResult:
    """Clone the repo at `ref` and extract everything we know how to extract."""
    result = AnalysisResult(app_name=app_name, commit_sha="")
    tmp = Path(tempfile.mkdtemp(prefix=f"sherlock-{app_name}-"))
    try:
        _clone(clone_url, ref, tmp)

        # Capture the HEAD SHA we actually cloned
        sha = subprocess.run(
            ["git", "-C", str(tmp), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        result.commit_sha = sha

        # Walk files once, dispatching by filename / extension
        for path in _walk(tmp):
            name = path.name
            ext = path.suffix.lower()
            try:
                if name == "pom.xml":
                    manifests.parse_pom(path, result)
                elif name == "requirements.txt":
                    manifests.parse_requirements_txt(path, result)
                elif name == "pyproject.toml":
                    manifests.parse_pyproject_toml(path, result)
                elif name == "package.json":
                    manifests.parse_package_json(path, result)
                elif name in {"openapi.yaml", "openapi.yml"}:
                    openapi.parse_openapi(path, result)
                elif name in {"asyncapi.yaml", "asyncapi.yml"}:
                    asyncapi.parse_asyncapi(path, result)
                elif ext == ".sql":
                    sql.parse_sql_file(path, result)
                elif ext in CODE_EXTS:
                    # All source files: embedded SQL + outbound HTTP hosts + shared-file I/O
                    sql.scan_code_for_sql(path, result)
                    code_refs.scan_for_outbound_hosts(path, result)
                    files.scan_file_io(path, result)
                    # Tree-sitter passes — additive AST extraction layered on top of the
                    # regex extractor. Each handles patterns regex misses for its language
                    # (URI-builder lambdas, variable-resolved URLs, object-form axios calls).
                    extractor = {
                        ".java":  treesitter_java.extract_calls,
                        ".py":    treesitter_python.extract_calls,
                        ".js":    treesitter_js.extract_calls,
                        ".mjs":   treesitter_js.extract_calls,
                        ".ts":    treesitter_js.extract_calls,
                    }.get(ext)
                    if extractor is not None:
                        try:
                            text = path.read_text(errors="ignore")
                            for host, method, p in extractor(text):
                                if host and host not in result.seen_hosts:
                                    result.seen_hosts.append(host)
                                triple = (host, method, p) if host else None
                                if triple and triple not in result.called_endpoints:
                                    result.called_endpoints.append(triple)
                        except Exception as exc:
                            log.warning("tree-sitter failed on %s: %s", path, exc)
                if ext in CONFIG_EXTS:
                    sql.scan_config_for_schema_ownership(path, result)
                    # config files often name feed paths too
                    files.scan_file_io(path, result)
            except Exception as exc:  # keep scanning other files on a single-file failure
                log.warning("parser failed on %s: %s", path, exc)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    return result


def _walk(root: Path):
    for p in root.rglob("*"):
        if p.is_dir():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        yield p
