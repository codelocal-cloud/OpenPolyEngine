-- Add validated BTC 5m provenance and query indexes to existing TimescaleDB.
ALTER TABLE market_observations
    ADD COLUMN IF NOT EXISTS slug TEXT,
    ADD COLUMN IF NOT EXISTS outcome TEXT;
CREATE INDEX IF NOT EXISTS market_observations_slug_time_idx
    ON market_observations (slug, observed_at DESC);
CREATE INDEX IF NOT EXISTS market_observations_book_idx
    ON market_observations (instrument, event_type, observed_at DESC);
