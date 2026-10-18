-- Deliberately separate simulated balances from any real execution system.
CREATE TABLE IF NOT EXISTS paper_accounts (
    account_id TEXT PRIMARY KEY CHECK (account_id IN ('demo', 'clob')),
    starting_cash NUMERIC(18,6) NOT NULL DEFAULT 1000 CHECK (starting_cash >= 0),
    cash_balance NUMERIC(18,6) NOT NULL DEFAULT 1000 CHECK (cash_balance >= 0),
    realized_pnl NUMERIC(18,6) NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
INSERT INTO paper_accounts (account_id) VALUES ('demo'), ('clob') ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS paper_positions (
    account_id TEXT NOT NULL REFERENCES paper_accounts(account_id),
    slug TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('UP','DOWN')),
    token_id TEXT NOT NULL,
    quantity NUMERIC(24,6) NOT NULL CHECK (quantity > 0),
    cost_basis NUMERIC(18,6) NOT NULL CHECK (cost_basis > 0),
    source TEXT NOT NULL CHECK (source IN ('synthetic_demo', 'polymarket_clob_ws')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (account_id, slug, outcome)
);

CREATE TABLE IF NOT EXISTS paper_orders (
    order_id UUID PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES paper_accounts(account_id),
    request_id UUID NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('BUY','SELL')),
    slug TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('UP','DOWN')),
    token_id TEXT NOT NULL,
    quantity NUMERIC(24,6) NOT NULL CHECK (quantity > 0),
    price NUMERIC(18,6) NOT NULL CHECK (price > 0 AND price < 1),
    notional NUMERIC(18,6) NOT NULL CHECK (notional > 0),
    fee NUMERIC(18,6) NOT NULL CHECK (fee >= 0),
    cash_delta NUMERIC(18,6) NOT NULL,
    realized_pnl NUMERIC(18,6),
    source TEXT NOT NULL CHECK (source IN ('synthetic_demo', 'polymarket_clob_ws')),
    quote_received_at TIMESTAMPTZ,
    request_fingerprint CHAR(64) NOT NULL,
    executed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(account_id, request_id)
);
CREATE INDEX IF NOT EXISTS paper_orders_recent_idx
    ON paper_orders (account_id, executed_at DESC);

CREATE TABLE IF NOT EXISTS paper_cash_ledger (
    entry_id UUID PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES paper_accounts(account_id),
    order_id UUID NOT NULL UNIQUE REFERENCES paper_orders(order_id),
    cash_delta NUMERIC(18,6) NOT NULL,
    balance_after NUMERIC(18,6) NOT NULL CHECK (balance_after >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
