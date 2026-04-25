# fraud-detection

Real-time fraud scoring driven by transaction events.

## Dependencies

- `account-service` (REST, for balance/status lookups)
- Redpanda/Kafka — consumes `banking.transactions.created`

## Contracts

- Events consumed: [asyncapi.yaml](./asyncapi.yaml)
