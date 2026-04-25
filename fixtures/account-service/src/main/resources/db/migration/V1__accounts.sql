CREATE TABLE IF NOT EXISTS accounts.accounts (
    id           VARCHAR(64)  PRIMARY KEY,
    customer_id  VARCHAR(64)  NOT NULL,
    status       VARCHAR(16)  NOT NULL,
    opened_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_accounts_customer ON accounts.accounts(customer_id);
