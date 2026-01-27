CREATE TABLE IF NOT EXISTS set_reservations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_id INTEGER NOT NULL,
  set_code TEXT NOT NULL,
  reserved_by TEXT,
  reserved_at TEXT NOT NULL,
  UNIQUE(batch_id, set_code),
  FOREIGN KEY(batch_id) REFERENCES batches(id)
);

CREATE INDEX IF NOT EXISTS idx_set_reservations_batch ON set_reservations(batch_id);
