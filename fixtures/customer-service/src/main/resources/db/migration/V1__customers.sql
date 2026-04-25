CREATE TABLE IF NOT EXISTS customers.customers (
    id          VARCHAR(64)  PRIMARY KEY,
    full_name   VARCHAR(256) NOT NULL,
    email       VARCHAR(256) NOT NULL UNIQUE,
    phone       VARCHAR(32),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);
