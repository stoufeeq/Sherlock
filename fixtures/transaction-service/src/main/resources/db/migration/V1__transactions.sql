CREATE TABLE IF NOT EXISTS transactions.transactions (
    id               VARCHAR(64)  PRIMARY KEY,
    from_account_id  VARCHAR(64)  NOT NULL,
    to_account_id    VARCHAR(64)  NOT NULL,
    amount           NUMERIC(19,4) NOT NULL,
    currency         VARCHAR(3)   NOT NULL,
    type             VARCHAR(16)  NOT NULL,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now()
);
