# account-service

Account CRUD and balance reads.

## Dependencies

- `shared-domain-lib` (Maven)
- Postgres schema `accounts` (owned)
- Postgres schema `ledger` (read-only — populated by `legacy-ledger` COBOL batch)

## Contracts

See [openapi.yaml](./openapi.yaml).

## Run

```bash
mvn spring-boot:run
```
