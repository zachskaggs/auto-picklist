-- CardKingdom buylist snapshot (only rows worth keeping: price_buy > 0)
CREATE TABLE IF NOT EXISTS ck_buylist (
  scryfall_id TEXT NOT NULL,
  is_foil     INTEGER NOT NULL,
  name TEXT,
  edition TEXT,
  sku TEXT,
  url TEXT,
  price_buy   REAL NOT NULL,
  qty_buying  INTEGER NOT NULL,
  PRIMARY KEY (scryfall_id, is_foil)
);
CREATE INDEX IF NOT EXISTS idx_ck_buylist_sid ON ck_buylist(scryfall_id);

-- ManaPool inventory snapshot (cards the seller currently has listed)
CREATE TABLE IF NOT EXISTS manapool_inventory (
  inventory_id TEXT PRIMARY KEY,
  scryfall_id TEXT,
  tcgplayer_sku INTEGER,
  name TEXT,
  set_code TEXT,
  collector_number TEXT,
  condition_id TEXT,
  finish_id TEXT,
  language_id TEXT,
  price_cents INTEGER,
  quantity INTEGER,
  fetched_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_mp_inv_sid ON manapool_inventory(scryfall_id);

-- Refresh log for CardKingdom buylist + ManaPool inventory syncs (mirrors manapool_sync_log)
CREATE TABLE IF NOT EXISTS ck_sync_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  status TEXT,
  summary_json TEXT,
  error_text TEXT
);

-- CardKingdom-specific snapshot columns on batch_items
ALTER TABLE batch_items ADD COLUMN mp_price REAL;
ALTER TABLE batch_items ADD COLUMN ck_price REAL;
ALTER TABLE batch_items ADD COLUMN ck_qty_buying INTEGER;
ALTER TABLE batch_items ADD COLUMN ck_ratio REAL;
ALTER TABLE batch_items ADD COLUMN is_foil INTEGER;
ALTER TABLE batch_items ADD COLUMN mp_inventory_id TEXT;
ALTER TABLE batch_items ADD COLUMN mp_tcgplayer_sku INTEGER;
ALTER TABLE batch_items ADD COLUMN mp_delisted INTEGER DEFAULT 0;
