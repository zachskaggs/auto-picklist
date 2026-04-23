CREATE TABLE IF NOT EXISTS session_names (
  user_session_id TEXT PRIMARY KEY,
  picker_name     TEXT NOT NULL,
  updated_at      TEXT NOT NULL
);
