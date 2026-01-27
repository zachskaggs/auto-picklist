ALTER TABLE batches ADD COLUMN source_payload TEXT;

CREATE TABLE IF NOT EXISTS manapool_orders_cache (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  order_id TEXT UNIQUE,
  raw_json TEXT NOT NULL,
  fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS manapool_sync_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  status TEXT,
  summary_json TEXT,
  error_text TEXT
);

CREATE INDEX IF NOT EXISTS idx_batch_items_scryfall_id ON batch_items(scryfall_id);
