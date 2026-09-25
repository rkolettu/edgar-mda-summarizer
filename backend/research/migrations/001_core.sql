-- Research store, phase 1: a generic filing model, sections and structured facts.
-- Every form type (10-K, 10-Q, 20-F, 40-F, 6-K, 8-K, amendments) shares these tables; nothing is keyed by form.

CREATE TABLE companies (
    company_id BIGSERIAL PRIMARY KEY,
    cik INTEGER NOT NULL UNIQUE,
    ticker TEXT,
    name TEXT,
    fiscal_year_end TEXT,                 -- 'MM-DD' as the filer states it; 52/53-week years end near it
    reporting_currency TEXT,
    accounting_standard TEXT,             -- us-gaap | ifrs | other
    is_showcase BOOLEAN NOT NULL DEFAULT FALSE,
    last_viewed_at TIMESTAMPTZ,           -- the storage guard evicts the least recently viewed non-showcase companies
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX companies_ticker_idx ON companies (ticker);

CREATE TABLE filings (
    filing_id BIGSERIAL PRIMARY KEY,
    company_id BIGINT NOT NULL REFERENCES companies ON DELETE CASCADE,
    accession_number TEXT NOT NULL UNIQUE,
    form_type TEXT NOT NULL,              -- as filed: '10-Q/A', '40-F', ...
    base_form TEXT NOT NULL,              -- without the amendment suffix
    is_amendment BOOLEAN NOT NULL DEFAULT FALSE,
    amends_filing_id BIGINT REFERENCES filings ON DELETE SET NULL,
    filing_date DATE NOT NULL,
    report_date DATE,                     -- EDGAR's period of report
    period_start DATE,                    -- fiscal-year-to-date span from the cover page (a Q2 10-Q covers six months)
    period_end DATE,
    fiscal_year INTEGER,
    fiscal_period TEXT,                   -- FY | Q1 | Q2 | Q3 | H1 | H2 ...
    period_months SMALLINT,
    is_annual BOOLEAN NOT NULL,
    is_interim BOOLEAN NOT NULL,
    accounting_standard TEXT,
    reporting_currency TEXT,
    fiscal_year_end TEXT,
    source_url TEXT NOT NULL,
    documents JSONB NOT NULL DEFAULT '[]',   -- [{url, role, type, ixbrl}]
    parser_version INTEGER NOT NULL,
    parser_confidence REAL,
    confidence_level TEXT,
    coverage JSONB NOT NULL DEFAULT '{}',    -- {category: {found, tier, confidence}}
    warnings JSONB NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'parsed',   -- parsed | extracted | analyzed | failed
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX filings_company_period_idx ON filings (company_id, period_end DESC);

CREATE TABLE filing_sections (
    section_id BIGSERIAL PRIMARY KEY,
    filing_id BIGINT NOT NULL REFERENCES filings ON DELETE CASCADE,
    parent_section_id BIGINT REFERENCES filing_sections ON DELETE CASCADE,
    category TEXT NOT NULL,               -- semantic category: commitments, debt, risk_factors, management_discussion ...
    source_kind TEXT NOT NULL,            -- xbrl_textblock | heading | exhibit | fulltext | llm
    source_label TEXT,                    -- 'us-gaap:DebtDisclosureTextBlock', 'item7', ...
    heading TEXT,
    document_url TEXT,
    element_id TEXT,
    ordinal INTEGER NOT NULL,
    char_count INTEGER NOT NULL,
    text_hash TEXT NOT NULL,
    text TEXT,                            -- NULL for nested blocks (their parent holds the text) and after retention pruning
    confidence REAL NOT NULL
);
CREATE INDEX filing_sections_filing_idx ON filing_sections (filing_id, category);

CREATE TABLE facts (
    fact_id BIGSERIAL PRIMARY KEY,
    company_id BIGINT NOT NULL REFERENCES companies ON DELETE CASCADE,
    filing_id BIGINT NOT NULL REFERENCES filings ON DELETE CASCADE,
    fact_key TEXT NOT NULL,               -- stable across filings: 'metric.revenue', 'commitment.supply_capacity'
    fact_type TEXT NOT NULL,              -- financial_metric | commitment | guarantee | debt | risk | ...
    category TEXT,
    subcategory TEXT,
    canonical_metric TEXT,
    label TEXT NOT NULL,
    reported_label TEXT,                  -- the line item as the filing words it
    xbrl_concept TEXT,
    dimensions JSONB NOT NULL DEFAULT '{}',
    dimensions_hash TEXT NOT NULL DEFAULT '',
    value_reported NUMERIC,               -- as displayed, before scale ('279' for $279 billion)
    reported_scale SMALLINT,              -- power of ten the display omits (9 = billions)
    reported_unit TEXT,                   -- iso4217:USD, iso4217:USD/xbrli:shares, xbrli:pure, xbrli:shares
    reported_currency TEXT,
    value_normalized NUMERIC,             -- full units: dollars, not millions; percentages as fractions
    normalized_unit TEXT,                 -- currency | currency_per_share | shares | ratio | other
    currency TEXT,
    decimals SMALLINT,
    accounting_standard TEXT,
    text_value TEXT,                      -- qualitative facts (strategy, risk, product changes)
    period_type TEXT NOT NULL,            -- instant | duration
    period_start DATE,
    period_end DATE NOT NULL,
    fiscal_year INTEGER,
    fiscal_period TEXT,
    period_months SMALLINT,
    is_comparative BOOLEAN NOT NULL DEFAULT FALSE,
    extraction_method TEXT NOT NULL,      -- xbrl | table | section_text | fulltext | llm
    parser_confidence REAL NOT NULL,
    confidence_level TEXT NOT NULL,       -- high | medium | low
    disclosure_status TEXT,               -- new | changed | repeated | resolved | removed (set by the comparison engine)
    materiality_score REAL,
    materiality_components JSONB,
    triggers TEXT[],
    pipeline_version INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE NULLS NOT DISTINCT (filing_id, fact_key, period_start, period_end, dimensions_hash)
);
CREATE INDEX facts_company_key_idx ON facts (company_id, fact_key, period_end);

CREATE TABLE fact_sources (
    source_id BIGSERIAL PRIMARY KEY,
    fact_id BIGINT NOT NULL REFERENCES facts ON DELETE CASCADE,
    filing_id BIGINT NOT NULL REFERENCES filings ON DELETE CASCADE,
    section_id BIGINT REFERENCES filing_sections ON DELETE SET NULL,
    category TEXT,
    heading TEXT,
    table_label TEXT,
    source_text TEXT,                     -- the table row or sentence the value appears in
    document_url TEXT,
    xbrl_element_id TEXT,                 -- fragment id in the filing document
    char_start INTEGER,
    char_end INTEGER
);
CREATE INDEX fact_sources_fact_idx ON fact_sources (fact_id);

-- One row per pipeline stage per filing: token accounting, and a lock so concurrent requests never pay twice.
CREATE TABLE analysis_runs (
    run_id BIGSERIAL PRIMARY KEY,
    filing_id BIGINT REFERENCES filings ON DELETE CASCADE,
    accession_number TEXT NOT NULL,
    stage TEXT NOT NULL,                  -- parse | extract | synthesize | audit
    pipeline_version INTEGER NOT NULL,
    model TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    status TEXT NOT NULL,                 -- running | succeeded | failed
    error TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ
);
CREATE UNIQUE INDEX analysis_runs_active_idx ON analysis_runs (accession_number, stage, pipeline_version)
    WHERE status IN ('running', 'succeeded');
