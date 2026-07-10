CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS sources (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  source_role TEXT NOT NULL,
  tier TEXT NOT NULL,
  type TEXT NOT NULL,
  category TEXT NOT NULL,
  url TEXT NOT NULL,
  homepage TEXT NOT NULL,
  allowed_domains JSONB NOT NULL DEFAULT '[]',
  fetch_interval_min INTEGER NOT NULL DEFAULT 60,
  language TEXT NOT NULL DEFAULT 'en',
  need_proxy BOOLEAN NOT NULL DEFAULT false,
  need_browser BOOLEAN NOT NULL DEFAULT false,
  can_be_main_source BOOLEAN NOT NULL DEFAULT true,
  affects_heat_score BOOLEAN NOT NULL DEFAULT false,
  is_active BOOLEAN NOT NULL DEFAULT true,
  config_json JSONB NOT NULL DEFAULT '{}',
  last_crawled_at TIMESTAMPTZ,
  last_success_at TIMESTAMPTZ,
  success_rate DOUBLE PRECISION NOT NULL DEFAULT 0,
  error_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS raw_articles (
  id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES sources(id),
  source_url TEXT NOT NULL,
  title TEXT NOT NULL,
  content TEXT NOT NULL DEFAULT '',
  author TEXT,
  language TEXT NOT NULL DEFAULT 'en',
  published_at TIMESTAMPTZ NOT NULL,
  crawled_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  title_hash TEXT NOT NULL,
  url_hash TEXT NOT NULL,
  raw_metadata JSONB NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'raw',
  skipped_reason TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS raw_articles_url_hash_idx ON raw_articles(url_hash);
CREATE INDEX IF NOT EXISTS raw_articles_title_hash_idx ON raw_articles(title_hash);

CREATE TABLE IF NOT EXISTS article_embeddings (
  id BIGSERIAL PRIMARY KEY,
  raw_article_id TEXT NOT NULL REFERENCES raw_articles(id),
  embedding_model TEXT NOT NULL,
  content_vector vector(1536),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS event_clusters (
  id TEXT PRIMARY KEY,
  main_article_id TEXT NOT NULL REFERENCES raw_articles(id),
  event_title TEXT NOT NULL,
  event_summary TEXT NOT NULL,
  category TEXT NOT NULL,
  tags JSONB NOT NULL DEFAULT '[]',
  final_score DOUBLE PRECISION NOT NULL DEFAULT 0,
  source_count INTEGER NOT NULL DEFAULT 1,
  first_seen_at TIMESTAMPTZ NOT NULL,
  last_seen_at TIMESTAMPTZ NOT NULL,
  status TEXT NOT NULL DEFAULT 'published',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS event_cluster_articles (
  id BIGSERIAL PRIMARY KEY,
  event_cluster_id TEXT NOT NULL REFERENCES event_clusters(id),
  raw_article_id TEXT NOT NULL REFERENCES raw_articles(id),
  similarity_score DOUBLE PRECISION NOT NULL DEFAULT 0,
  is_main BOOLEAN NOT NULL DEFAULT false,
  source_priority INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS processed_articles (
  id BIGSERIAL PRIMARY KEY,
  raw_article_id TEXT NOT NULL REFERENCES raw_articles(id),
  event_cluster_id TEXT REFERENCES event_clusters(id),
  ai_relevance DOUBLE PRECISION NOT NULL,
  novelty DOUBLE PRECISION NOT NULL,
  impact DOUBLE PRECISION NOT NULL,
  information_density DOUBLE PRECISION NOT NULL,
  actionability DOUBLE PRECISION NOT NULL,
  creator_value DOUBLE PRECISION NOT NULL,
  base_score DOUBLE PRECISION NOT NULL,
  final_score DOUBLE PRECISION NOT NULL,
  title_zh TEXT NOT NULL,
  one_line_summary TEXT NOT NULL,
  summary_zh TEXT NOT NULL,
  reason_zh TEXT NOT NULL,
  action_zh TEXT NOT NULL,
  category TEXT NOT NULL,
  tags JSONB NOT NULL DEFAULT '[]',
  model_used TEXT,
  generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  status TEXT NOT NULL DEFAULT 'processed',
  rejection_reason TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS daily_reports (
  id BIGSERIAL PRIMARY KEY,
  report_date DATE NOT NULL UNIQUE,
  title TEXT NOT NULL,
  summary TEXT NOT NULL,
  sections JSONB NOT NULL DEFAULT '{}',
  article_count INTEGER NOT NULL DEFAULT 0,
  markdown TEXT NOT NULL DEFAULT '',
  generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  published_at TIMESTAMPTZ,
  status TEXT NOT NULL DEFAULT 'generated',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
  id BIGSERIAL PRIMARY KEY,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at TIMESTAMPTZ,
  status TEXT NOT NULL,
  raw_count INTEGER NOT NULL DEFAULT 0,
  processed_count INTEGER NOT NULL DEFAULT 0,
  cluster_count INTEGER NOT NULL DEFAULT 0,
  skipped_reasons JSONB NOT NULL DEFAULT '{}',
  error TEXT
);


CREATE TABLE IF NOT EXISTS period_reports (
  id BIGSERIAL PRIMARY KEY,
  kind TEXT NOT NULL,
  period_key TEXT NOT NULL,
  range_start DATE NOT NULL,
  range_end DATE NOT NULL,
  mainline_title TEXT NOT NULL DEFAULT '',
  mainline_body TEXT NOT NULL DEFAULT '',
  theme_notes JSONB NOT NULL DEFAULT '[]',
  article_count INTEGER NOT NULL DEFAULT 0,
  report_dates JSONB NOT NULL DEFAULT '[]',
  generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  status TEXT NOT NULL DEFAULT 'generated',
  UNIQUE (kind, period_key)
);
