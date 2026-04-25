"""DDL and DML extraction for SQL and COBOL EXEC SQL.

Heuristic regex — good enough for the fixture corpus, not a full SQL parser.
"""

import re
from pathlib import Path

from app.models import AnalysisResult

# ---- DDL (run on .sql files) --------------------------------------------------
CREATE_TABLE_RE = re.compile(
    r"create\s+table\s+(?:if\s+not\s+exists\s+)?([a-z_][\w]*)\.([a-z_][\w]*)",
    re.IGNORECASE,
)

# ---- DML (run on source code) -------------------------------------------------
# Same-line whitespace only (\s would cross newlines)
_H = r"[ \t]+"
READ_TABLE_RE = re.compile(
    rf"\b(?:from|join){_H}([a-z_][\w]*)\.([a-z_][\w]*)",
    re.IGNORECASE,
)
WRITE_TABLE_RE = re.compile(
    rf"\b(?:insert{_H}into|update|delete{_H}from|merge{_H}into){_H}([a-z_][\w]*)\.([a-z_][\w]*)",
    re.IGNORECASE,
)

# ---- Schema ownership (run on config files) ----------------------------------
# Flyway yml:  schemas: foo  /  default-schema: foo   (same-line value required)
FLYWAY_SCHEMAS_RE = re.compile(
    r"(?m)^[ \t]*(?:schemas|default-schema)[ \t]*:[ \t]*([a-z_][\w]*)[ \t]*$",
    re.IGNORECASE,
)
# JDBC-style DSN:  ?currentSchema=foo
JDBC_SCHEMA_RE = re.compile(r"currentSchema=([a-z_][\w]*)", re.IGNORECASE)


def parse_sql_file(path: Path, result: AnalysisResult) -> None:
    text = path.read_text(errors="ignore")
    for schema, table in CREATE_TABLE_RE.findall(text):
        fqn = f"{schema.lower()}.{table.lower()}"
        if fqn not in result.created_tables:
            result.created_tables.append(fqn)
        if schema.lower() not in result.owned_schemas:
            result.owned_schemas.append(schema.lower())


def _line_context(text: str, pos: int) -> str:
    line_start = text.rfind("\n", 0, pos) + 1
    line_end = text.find("\n", pos)
    return text[line_start:line_end if line_end >= 0 else len(text)]


def _looks_like_import(line: str) -> bool:
    """Filter out Python/Java `from X.Y import Z` which falsely match `from table.column`."""
    return bool(re.search(r"\b(?:^\s*import\b|\bimport\s)", line))


def scan_code_for_sql(path: Path, result: AnalysisResult) -> None:
    """Scan non-SQL source files (Java, Python, COBOL) for embedded SQL."""
    text = path.read_text(errors="ignore")
    for m in READ_TABLE_RE.finditer(text):
        if _looks_like_import(_line_context(text, m.start())):
            continue
        fqn = f"{m.group(1).lower()}.{m.group(2).lower()}"
        if fqn not in result.read_tables:
            result.read_tables.append(fqn)
    for m in WRITE_TABLE_RE.finditer(text):
        if _looks_like_import(_line_context(text, m.start())):
            continue
        fqn = f"{m.group(1).lower()}.{m.group(2).lower()}"
        if fqn not in result.written_tables:
            result.written_tables.append(fqn)


def scan_config_for_schema_ownership(path: Path, result: AnalysisResult) -> None:
    """application.yml / .properties — detect Flyway schema ownership."""
    text = path.read_text(errors="ignore")
    for schema in FLYWAY_SCHEMAS_RE.findall(text):
        s = schema.lower()
        if s not in result.owned_schemas:
            result.owned_schemas.append(s)
    for schema in JDBC_SCHEMA_RE.findall(text):
        s = schema.lower()
        if s not in result.owned_schemas:
            result.owned_schemas.append(s)
