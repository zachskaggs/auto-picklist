CREATE TABLE IF NOT EXISTS migrations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS batches (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open',
  source TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS batch_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_id INTEGER NOT NULL,
  game TEXT NOT NULL,
  set_code TEXT NOT NULL,
  card_name TEXT NOT NULL,
  collector_number TEXT,
  scryfall_id TEXT,
  qty_required INTEGER NOT NULL,
  qty_picked INTEGER NOT NULL DEFAULT 0,
  condition TEXT,
  language TEXT,
  printing TEXT,
  is_missing INTEGER NOT NULL DEFAULT 0,
  missing_note TEXT,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(batch_id) REFERENCES batches(id)
);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  type TEXT NOT NULL,
  batch_item_id INTEGER NOT NULL,
  qty INTEGER NOT NULL,
  timestamp TEXT NOT NULL,
  user_session_id TEXT,
  FOREIGN KEY(batch_item_id) REFERENCES batch_items(id)
);

CREATE TABLE IF NOT EXISTS card_cache (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  scryfall_id TEXT UNIQUE,
  card_name TEXT,
  set_code TEXT,
  collector_number TEXT,
  data_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS set_bins (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  game TEXT NOT NULL,
  set_code TEXT NOT NULL,
  location TEXT NOT NULL,
  note TEXT,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_batch_items_batch ON batch_items(batch_id);
CREATE INDEX IF NOT EXISTS idx_batch_items_game_set ON batch_items(game, set_code);
CREATE INDEX IF NOT EXISTS idx_batch_items_name ON batch_items(card_name);
CREATE INDEX IF NOT EXISTS idx_events_item ON events(batch_item_id);
CREATE INDEX IF NOT EXISTS idx_set_bins ON set_bins(game, set_code);
