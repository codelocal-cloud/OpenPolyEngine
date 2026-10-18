-- First-class PostgreSQL 17 + TimescaleDB persistence.
-- Applied explicitly by: python -m services.market_data.migrate
-- TimescaleDB is required: do not silently fall back to a regular table.
CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS market_snapshots (
    slug TEXT NOT NULL CHECK (slug ~ '^btc-updown-5m-[0-9]+$'),
    fetched_at TIMESTAMPTZ NOT NULL,
    market_id TEXT NOT NULL,
    slot_start TIMESTAMPTZ NOT NULL,
    slot_end TIMESTAMPTZ NOT NULL,
    token_up TEXT NOT NULL,
    token_down TEXT NOT NULL,
    price_up NUMERIC(20,12) NULL,
    price_down NUMERIC(20,12) NULL,
    active BOOLEAN NOT NULL,
    closed BOOLEAN NOT NULL,
    accepting_orders BOOLEAN NOT NULL,
    data_source TEXT NOT NULL,
    resolution_source TEXT NULL,
    payload_json JSONB NOT NULL,
    PRIMARY KEY (slug, fetched_at),
    CHECK (slot_end = slot_start + INTERVAL '5 minutes'),
    CHECK (token_up <> token_down),
    CHECK (price_up IS NULL OR price_up BETWEEN 0 AND 1),
    CHECK (price_down IS NULL OR price_down BETWEEN 0 AND 1)
);

SELECT create_hypertable('market_snapshots', by_range('fetched_at'), if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS market_snapshots_slot_idx ON market_snapshots (slot_start DESC, fetched_at DESC);
CREATE INDEX IF NOT EXISTS market_snapshots_source_idx ON market_snapshots (data_source, fetched_at DESC);

-- These are research-grade raw events; retention and compression are added only
-- after a measured data growth / backtest retention policy is agreed.
