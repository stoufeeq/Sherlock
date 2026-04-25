# notification-service

Email/SMS fanout driven by transaction and customer events.

## Dependencies

- `shared-domain-lib` (Maven)
- `customer-service` (REST, to look up email/phone)
- Redpanda/Kafka — consumes `banking.transactions.created` and `banking.customers.updated`

## Contracts

- Events consumed: [asyncapi.yaml](./asyncapi.yaml)
