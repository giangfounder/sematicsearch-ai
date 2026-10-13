-- Dòng dữ liệu gốc (đúng tên cột trong file import) để API "bảng" trả về nguyên 1 row
ALTER TABLE products ADD COLUMN IF NOT EXISTS raw jsonb NOT NULL DEFAULT '{}';
