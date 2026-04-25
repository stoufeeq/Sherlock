-- Owned by legacy-ledger; read by account-service and analytics-service.
CREATE TABLE IF NOT EXISTS ledger.balances (
    id         BIGSERIAL     PRIMARY KEY,
    account_id VARCHAR(64)   NOT NULL,
    amount     NUMERIC(19,4) NOT NULL,
    currency   VARCHAR(3)    NOT NULL,
    posted_at  TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_balances_account ON ledger.balances(account_id, posted_at DESC);
