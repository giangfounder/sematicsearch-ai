-- Khoá API riêng cho từng bảng. Chỉ lưu sha256 của khoá; khoá gốc hiện 1 lần khi tạo.
CREATE TABLE IF NOT EXISTS table_keys (
  id           serial PRIMARY KEY,
  demo_id      int NOT NULL REFERENCES demos ON DELETE CASCADE,
  name         text NOT NULL,
  prefix       text NOT NULL,
  key_hash     text NOT NULL UNIQUE,
  scopes       text[] NOT NULL DEFAULT '{read}',
  active       bool NOT NULL DEFAULT true,
  expires_at   timestamptz,
  created_at   timestamptz NOT NULL DEFAULT now(),
  last_used_at timestamptz,
  use_count    bigint NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS table_keys_demo_idx ON table_keys (demo_id);
