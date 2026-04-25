# customer-service

Customer profile CRUD + CustomerUpdated events.

## Dependencies

- `shared-domain-lib` (Maven)
- Postgres schema `customers` (owned)
- Redpanda/Kafka — publishes `banking.customers.updated`

## Contracts

- REST: [openapi.yaml](./openapi.yaml)
- Events: [asyncapi.yaml](./asyncapi.yaml)
