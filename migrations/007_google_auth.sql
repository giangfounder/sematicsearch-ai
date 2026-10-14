-- Đăng nhập bằng Google: tài khoản có thể không có mật khẩu; lưu định danh Google + ảnh đại diện.
ALTER TABLE accounts ALTER COLUMN pass_salt DROP NOT NULL;
ALTER TABLE accounts ALTER COLUMN pass_hash DROP NOT NULL;
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS google_sub text;
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS avatar_url text;
CREATE UNIQUE INDEX IF NOT EXISTS accounts_google_sub_idx ON accounts (google_sub) WHERE google_sub IS NOT NULL;
