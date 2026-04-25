"""Reads the nightly ledger report produced by legacy-ledger and publishes
regulator-bound aggregates.

File contract:
  Path:   /shared/reports/LEDGER.RPT
  Format: legacy-ledger writes a trailer line `POSTED RECORDS: NNN` followed
          by per-account summaries.

If legacy-ledger changes this path or the trailer format, this reader breaks.
"""

from pathlib import Path

LEDGER_REPORT_PATH = Path("/shared/reports/LEDGER.RPT")


def read_daily_summary() -> dict:
    if not LEDGER_REPORT_PATH.exists():
        return {"status": "no_report", "path": str(LEDGER_REPORT_PATH)}
    with open(LEDGER_REPORT_PATH, "r") as f:
        text = f.read()
    posted = 0
    for line in text.splitlines():
        if line.startswith("POSTED RECORDS:"):
            posted = int(line.split(":", 1)[1].strip())
            break
    return {"status": "ok", "path": str(LEDGER_REPORT_PATH), "posted_records": posted}
