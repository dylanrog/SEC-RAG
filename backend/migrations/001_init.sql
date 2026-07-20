CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE companies (
  cik    bigint PRIMARY KEY,
  ticker text UNIQUE NOT NULL,
  name   text NOT NULL
);

CREATE TABLE filings (
  id          bigserial PRIMARY KEY,
  cik         bigint NOT NULL REFERENCES companies (cik),
  accession   text UNIQUE NOT NULL,
  form_type   text NOT NULL,
  filing_date date NOT NULL,
  period_end  date,
  viewer_html text NOT NULL
);

CREATE TABLE sentences (
  filing_id  bigint NOT NULL REFERENCES filings (id),
  sid        integer NOT NULL,
  section    text NOT NULL,
  text       text NOT NULL,
  char_start integer NOT NULL,
  char_end   integer NOT NULL,
  PRIMARY KEY (filing_id, sid)
);

CREATE TABLE chunks (
  id          bigserial PRIMARY KEY,
  filing_id   bigint NOT NULL REFERENCES filings (id),
  section     text NOT NULL,
  sid_start   integer NOT NULL,
  sid_end     integer NOT NULL,
  text        text NOT NULL,
  token_count integer NOT NULL,
  embedding   vector(384) NOT NULL
);

CREATE INDEX chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX chunks_text_fts ON chunks USING gin (to_tsvector('english', text));
CREATE INDEX filings_cik_idx ON filings (cik);
