CREATE TABLE IF NOT EXISTS demos (
  id            serial PRIMARY KEY,
  slug          text UNIQUE NOT NULL,
  name          text NOT NULL,
  industry      text,
  data_version  bigint NOT NULL DEFAULT 1,
  embed_model   text NOT NULL DEFAULT 'gemini-embedding-001',
  embed_dim     int  NOT NULL DEFAULT 768,
  thresholds    jsonb NOT NULL DEFAULT '{}',
  settings      jsonb NOT NULL DEFAULT '{}',
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS attribute_definitions (
  id             serial PRIMARY KEY,
  demo_id        int NOT NULL REFERENCES demos ON DELETE CASCADE,
  key            text NOT NULL,
  label          text NOT NULL,
  type           text NOT NULL CHECK (type IN ('text','number','enum','multi_enum','bool')),
  unit           text,
  unit_aliases   text[] NOT NULL DEFAULT '{}',
  label_aliases  text[] NOT NULL DEFAULT '{}',
  enum_values    jsonb NOT NULL DEFAULT '[]',
  filterable     bool NOT NULL DEFAULT false,
  searchable     bool NOT NULL DEFAULT true,
  weight         real NOT NULL DEFAULT 0.5 CHECK (weight BETWEEN 0 AND 1),
  display_order  int  NOT NULL DEFAULT 0,
  UNIQUE (demo_id, key)
);

CREATE TABLE IF NOT EXISTS products (
  id                 serial PRIMARY KEY,
  demo_id            int NOT NULL REFERENCES demos ON DELETE CASCADE,
  sku                text NOT NULL,
  name               text NOT NULL,
  category           text,
  brand              text,
  price              double precision,
  price_unit         text,
  in_stock           bool NOT NULL DEFAULT true,
  short_description  text,
  description        text,
  attributes         jsonb NOT NULL DEFAULT '{}',
  aliases            text[] NOT NULL DEFAULT '{}',
  use_cases          text[] NOT NULL DEFAULT '{}',
  sample_questions   text[] NOT NULL DEFAULT '{}',
  enrichment_status  text NOT NULL DEFAULT 'none' CHECK (enrichment_status IN ('none','ai_draft','reviewed')),
  extra              jsonb NOT NULL DEFAULT '{}',
  updated_at         timestamptz NOT NULL DEFAULT now(),
  UNIQUE (demo_id, sku)
);
CREATE INDEX IF NOT EXISTS products_demo_idx ON products (demo_id);

CREATE TABLE IF NOT EXISTS product_vectors (
  id           bigserial PRIMARY KEY,
  product_id   int NOT NULL REFERENCES products ON DELETE CASCADE,
  kind         text NOT NULL CHECK (kind IN ('name','profile','use_case','question')),
  source_text  text NOT NULL,
  text_hash    text NOT NULL,
  embed_model  text NOT NULL,
  vec_int8     bytea NOT NULL,
  scale        real NOT NULL,
  vec_f32      bytea,
  UNIQUE (product_id, kind, text_hash)
);
CREATE INDEX IF NOT EXISTS product_vectors_product_idx ON product_vectors (product_id);

CREATE TABLE IF NOT EXISTS eval_cases (
  id                    serial PRIMARY KEY,
  demo_id               int NOT NULL REFERENCES demos ON DELETE CASCADE,
  query                 text NOT NULL,
  context               jsonb,
  expected_product_ids  int[] NOT NULL DEFAULT '{}',
  expected_status       text NOT NULL CHECK (expected_status IN ('matched','ambiguous','no_match','out_of_scope')),
  category              text,
  split                 text NOT NULL DEFAULT 'test' CHECK (split IN ('dev','test')),
  source                text NOT NULL CHECK (source IN ('manual','ai','log')),
  active                bool NOT NULL DEFAULT true,
  created_at            timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS eval_cases_demo_idx ON eval_cases (demo_id, split);

CREATE TABLE IF NOT EXISTS search_logs (
  id              bigserial PRIMARY KEY,
  demo_id         int NOT NULL,
  request_id      text UNIQUE NOT NULL,
  text            text NOT NULL,
  context         jsonb,
  understanding   jsonb,
  candidates      jsonb,
  status          text,
  product_ids     int[],
  reranked        bool,
  cache_hit       bool,
  fallback_reason text,
  latency         jsonb,
  data_version    bigint,
  feedback        jsonb,
  created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS search_logs_demo_idx ON search_logs (demo_id, created_at DESC);

CREATE TABLE IF NOT EXISTS jobs (
  id          text PRIMARY KEY,
  demo_id     int,
  kind        text NOT NULL,
  status      text NOT NULL,
  progress    real NOT NULL DEFAULT 0,
  params      jsonb,
  result      jsonb,
  error       text,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS gemini_usage (
  day            date NOT NULL,
  demo_id        int NOT NULL DEFAULT 0,
  call_type      text NOT NULL,
  model          text NOT NULL,
  calls          int NOT NULL DEFAULT 0,
  input_tokens   bigint NOT NULL DEFAULT 0,
  output_tokens  bigint NOT NULL DEFAULT 0,
  errors         int NOT NULL DEFAULT 0,
  PRIMARY KEY (day, demo_id, call_type, model)
);
