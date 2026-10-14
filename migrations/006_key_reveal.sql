-- Giữ hash để xác thực, chỉ thêm bản mã cho các khóa tạo mới có cấu hình mã hóa.
-- Khóa cũ không thể khôi phục từ hash và để key_encrypted NULL.
ALTER TABLE table_keys ADD COLUMN IF NOT EXISTS key_encrypted bytea;
