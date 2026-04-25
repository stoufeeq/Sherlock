# legacy-ledger

Nightly batch ledger postings. Written in COBOL, ported to Linux via GnuCOBOL.

## What it does

1. Reads incoming postings from a flat file in `/shared/postings/YYYYMMDD.DAT`
   (CICS/mainframe leftovers — the modern apps dump postings here via SFTP).
2. Computes per-account balances and writes them to the Postgres `ledger.balances` table.
3. Emits a processing report to `/shared/reports/YYYYMMDD.RPT`.

## Downstream consumers

- `account-service` — reads `ledger.balances` for the `GET /accounts/{id}/balance` endpoint.
- `analytics-service` — joins `ledger.balances` into customer summaries.

**A schema change here silently breaks both.** This is exactly the kind of edge
Sherlock must surface.

## Build

```bash
cobc -x src/LEDGER.cbl -o build/ledger
```
