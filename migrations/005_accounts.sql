-- Tài khoản đăng nhập + phiên; bảng (demos) thuộc sở hữu tài khoản.
CREATE TABLE IF NOT EXISTS accounts (
  id          serial PRIMARY KEY,
  email       text UNIQUE NOT NULL,
  name        text,
  phone       text,
  pass_salt   text NOT NULL,
  pass_hash   text NOT NULL,
  is_admin    bool NOT NULL DEFAULT false,
  active      bool NOT NULL DEFAULT true,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sessions (
  token_hash   text PRIMARY KEY,
  account_id   int NOT NULL REFERENCES accounts ON DELETE CASCADE,
  remember     bool NOT NULL DEFAULT false,
  created_at   timestamptz NOT NULL DEFAULT now(),
  expires_at   timestamptz NOT NULL,
  last_seen_at timestamptz
);
CREATE INDEX IF NOT EXISTS sessions_account_idx ON sessions (account_id);

ALTER TABLE demos ADD COLUMN IF NOT EXISTS account_id int REFERENCES accounts ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS demos_account_idx ON demos (account_id);
