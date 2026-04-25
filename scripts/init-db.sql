-- Shared Postgres schemas for the 10 banking fixture apps.
-- Each service owns one schema; analytics reads across them; ledger is written by COBOL.

CREATE SCHEMA IF NOT EXISTS ledger;
CREATE SCHEMA IF NOT EXISTS accounts;
CREATE SCHEMA IF NOT EXISTS transactions;
CREATE SCHEMA IF NOT EXISTS customers;
CREATE SCHEMA IF NOT EXISTS notifications;

GRANT ALL ON SCHEMA ledger, accounts, transactions, customers, notifications TO banking;
