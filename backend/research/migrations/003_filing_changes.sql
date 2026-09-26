-- Phase 3: every scored change between a company's latest filing and the reports before it.
-- Recomputed in code whenever the company's filings change; the Filing Changes tab and later model stages read it.

CREATE TABLE filing_changes (
    change_id BIGSERIAL PRIMARY KEY,
    company_id BIGINT NOT NULL REFERENCES companies ON DELETE CASCADE,
    filing_id BIGINT NOT NULL REFERENCES filings ON DELETE CASCADE,
    base_filing_id BIGINT REFERENCES filings ON DELETE SET NULL,
    comparison TEXT NOT NULL,             -- sequential | vs_annual | annual_vs_annual | year_over_year
    kind TEXT NOT NULL,                   -- numeric | derived | narrative
    change_type TEXT NOT NULL,            -- new | changed | removed
    category TEXT NOT NULL,
    label TEXT NOT NULL,
    fact_key TEXT,
    fact_id BIGINT REFERENCES facts ON DELETE SET NULL,
    base_fact_id BIGINT REFERENCES facts ON DELETE SET NULL,
    section_id BIGINT REFERENCES filing_sections ON DELETE SET NULL,
    value NUMERIC,
    base_value NUMERIC,
    annual_value NUMERIC,
    change REAL,                          -- relative change, or percentage points / days for derived metrics
    unit TEXT,
    currency TEXT,
    period_label TEXT,
    base_period_label TEXT,
    text TEXT,                            -- new wording (old wording for a removal)
    base_text TEXT,
    triggers JSONB NOT NULL DEFAULT '[]',
    flags TEXT[],
    materiality_score REAL NOT NULL,
    materiality_components JSONB NOT NULL,
    reasons JSONB NOT NULL DEFAULT '[]',
    tier TEXT NOT NULL,                   -- top | notable | background
    details JSONB NOT NULL DEFAULT '{}',  -- series, source, kind of wording change
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX filing_changes_company_idx ON filing_changes (company_id, materiality_score DESC);
