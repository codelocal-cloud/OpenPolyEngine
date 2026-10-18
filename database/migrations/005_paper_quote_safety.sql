-- Quote freshness checks need latest book-changing event by receive time.
-- The collector records price_change, tick_size_change and best_bid_ask separately;
-- paper execution must not use a prior book when these updates are unreconciled.
CREATE INDEX IF NOT EXISTS market_observations_paper_quote_idx
ON market_observations (instrument, slug, received_at DESC)
WHERE source = 'polymarket_clob_ws'
  AND event_type IN ('book','price_change','best_bid_ask','tick_size_change');
