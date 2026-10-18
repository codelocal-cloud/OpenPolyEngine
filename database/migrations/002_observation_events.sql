-- High-cardinality observations for future market feeds. The current scanner
-- does not write fabricated order-book or oracle data.
CREATE TABLE IF NOT EXISTS market_observations (
    observed_at TIMESTAMPTZ NOT NULL,
    received_at TIMESTAMPTZ NOT NULL,
    source TEXT NOT NULL,
    instrument TEXT NOT NULL,
    event_type TEXT NOT NULL,
    source_event_id TEXT NOT NULL,
    payload JSONB NOT NULL,
    PRIMARY KEY (source, source_event_id, observed_at),
    CHECK (received_at >= observed_at - INTERVAL '5 minutes')
);
SELECT create_hypertable('market_observations', by_range('observed_at'), if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS market_observations_instrument_idx ON market_observations (instrument, observed_at DESC);
