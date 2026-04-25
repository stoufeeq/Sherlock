# transaction-service

Money movement + event publishing.

## Dependencies

- `shared-domain-lib` (Maven)
- `account-service` (REST, via `ACCOUNT_SERVICE_URL`)
- Postgres schema `transactions` (owned)
- Redpanda/Kafka — publishes `banking.transactions.created`
- Shared file feed — writes `/shared/postings/POSTINGS.DAT` nightly at 01:00 (consumed by `legacy-ledger`)

## Contracts

- REST: [openapi.yaml](./openapi.yaml)
- Events: [asyncapi.yaml](./asyncapi.yaml)
