# analytics-service

Reporting and cross-schema aggregates over the banking platform.

## Dependencies

- Postgres — **reads** schemas `accounts`, `transactions`, `customers`, `ledger`
  (this is the silent coupling: DDL changes in those services can break reports)
- Shared file feed — **reads** `/shared/reports/LEDGER.RPT` (written by `legacy-ledger`)

## Contracts

- REST: [openapi.yaml](./openapi.yaml)
