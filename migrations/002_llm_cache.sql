-- Cache bền cho embedding câu hỏi và kết quả hiểu câu: tránh gọi lại Gemini khi restart / chạy evaluate nhiều lần
CREATE TABLE IF NOT EXISTS llm_cache (
  key         text PRIMARY KEY,
  kind        text NOT NULL,          -- embed | understand
  value       jsonb,
  vec         bytea,
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS llm_cache_created_idx ON llm_cache (created_at);
