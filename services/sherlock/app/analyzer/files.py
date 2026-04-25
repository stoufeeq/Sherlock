"""Detect file-feed coupling — when one app writes a file on a shared volume
and another app reads it. Covers Java, Python, JS/TS, COBOL, and YAML config.

Heuristic regex — good enough for fixture corpus. The detection rule:
  1. Find every absolute path string literal on a shared volume (paths starting
     with /shared/ by convention; configurable via SHARED_PREFIXES).
  2. Classify as read / write by inspecting a ±180-char window for language
     idioms (FileInputStream / "w" / writeFile / OPEN OUTPUT etc).
  3. COBOL gets a dedicated pass that follows SELECT/ASSIGN + OPEN INPUT/OUTPUT
     semantics properly via a two-step scan.
"""

import re
from pathlib import Path

from app.models import AnalysisResult

# Paths worth treating as inter-app file feeds. Tweak / extend in the enterprise.
SHARED_PREFIXES = ("/shared/", "/mnt/feeds/", "/feeds/", "/inbound/", "/outbound/",
                   "/var/feeds/", "/opt/batch/")

# A string literal containing a path on a shared volume
FEED_PATH_RE = re.compile(
    r'["\']('
    + r'|'.join(re.escape(p) + r'[A-Za-z0-9._/\-{}\*]+' for p in SHARED_PREFIXES)
    + r')["\']'
)

READ_MARKERS = (
    # Java
    "FileInputStream", "FileReader", "BufferedReader", "newBufferedReader",
    "Files.readAll", "Files.lines", "Files.newInputStream",
    # Python
    "read_csv", "read_json", "read_parquet", "readlines", "read_text",
    '"r"', "'r'", '"rb"', "'rb'",
    # JS / Node
    "createReadStream", "readFile", "readFileSync",
    # COBOL (scanned separately, but include for non-COBOL files that embed COBOL keywords)
    "OPEN INPUT",
    # Generic English indicator
    " read ", "reader", "Reader ",
)

WRITE_MARKERS = (
    # Java
    "FileOutputStream", "FileWriter", "BufferedWriter", "PrintWriter",
    "newBufferedWriter", "Files.write", "Files.writeString", "Files.newOutputStream",
    # Python
    "to_csv", "to_json", "to_parquet", "write_text",
    '"w"', "'w'", '"wb"', "'wb'", '"a"', "'a'", '"ab"', "'ab'",
    # JS / Node
    "createWriteStream", "writeFile", "writeFileSync", "appendFile", "appendFileSync",
    # COBOL
    "OPEN OUTPUT", "OPEN I-O", "OPEN EXTEND",
    # Generic
    "writer", "Writer ", " write ",
)


# ---- COBOL-specific (authoritative — use SELECT/ASSIGN and OPEN verbs) -------
COBOL_SELECT_RE = re.compile(
    r'SELECT\s+([A-Za-z0-9\-]+)\s+ASSIGN\s+TO\s+"([^"]+)"',
    re.IGNORECASE,
)
COBOL_OPEN_RE = re.compile(
    r'OPEN\s+(INPUT|OUTPUT|I-O|EXTEND)\s+([A-Za-z0-9\-,\s]+?)(?:\.|\n)',
    re.IGNORECASE,
)


def _is_shared(path: str) -> bool:
    return any(path.startswith(p) for p in SHARED_PREFIXES)


def _classify(text: str, match_start: int, match_end: int) -> str | None:
    window = text[max(0, match_start - 180):match_end + 180]
    has_read = any(k in window for k in READ_MARKERS)
    has_write = any(k in window for k in WRITE_MARKERS)
    if has_write and not has_read:
        return "write"
    if has_read and not has_write:
        return "read"
    if has_read and has_write:
        return "both"
    return None


def _add(result: AnalysisResult, path: str, direction: str) -> None:
    if direction in ("read", "both") and path not in result.read_files:
        result.read_files.append(path)
    if direction in ("write", "both") and path not in result.written_files:
        result.written_files.append(path)


def scan_file_io(path: Path, result: AnalysisResult) -> None:
    """Scan a single source or config file for shared-volume file I/O."""
    text = path.read_text(errors="ignore")
    ext = path.suffix.lower()

    if ext in {".cbl", ".cob", ".cobol"}:
        _scan_cobol(text, result)
        return

    # Non-COBOL: scan every shared-path literal, classify by nearby keywords.
    for m in FEED_PATH_RE.finditer(text):
        p = m.group(1)
        direction = _classify(text, m.start(), m.end())
        if direction:
            _add(result, p, direction)


def _scan_cobol(text: str, result: AnalysisResult) -> None:
    # logical-name -> path
    bindings: dict[str, str] = {}
    for m in COBOL_SELECT_RE.finditer(text):
        name = m.group(1).upper()
        path = m.group(2)
        if _is_shared(path):
            bindings[name] = path

    for m in COBOL_OPEN_RE.finditer(text):
        mode = m.group(1).upper()
        # "OPEN INPUT A, B." may list multiple files; split on commas/whitespace.
        names = re.split(r"[,\s]+", m.group(2).strip())
        for raw in names:
            n = raw.upper()
            path = bindings.get(n)
            if not path:
                continue
            if mode == "INPUT":
                _add(result, path, "read")
            elif mode == "OUTPUT" or mode == "EXTEND":
                _add(result, path, "write")
            elif mode == "I-O":
                _add(result, path, "both")
