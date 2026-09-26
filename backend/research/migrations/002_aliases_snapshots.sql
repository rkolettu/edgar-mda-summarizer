-- Phase 2: renamed categories and the stored per-company research snapshot the tabs read.

-- A company renamed a category (XBRL member or concept) between filings; old_key's history continues under new_key.
CREATE TABLE member_aliases (
    company_id BIGINT NOT NULL REFERENCES companies ON DELETE CASCADE,
    old_key TEXT NOT NULL,
    new_key TEXT NOT NULL,
    method TEXT NOT NULL,                 -- comparative_period (code) | llm (phase 5)
    evidence JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (company_id, old_key)
);

-- One payload per company with every tab's data, rebuilt deterministically when its filings change.
CREATE TABLE research_snapshots (
    company_id BIGINT PRIMARY KEY REFERENCES companies ON DELETE CASCADE,
    as_of_filing_id BIGINT REFERENCES filings ON DELETE SET NULL,
    snapshot_version INTEGER NOT NULL,
    parser_version INTEGER NOT NULL,
    payload JSONB NOT NULL,
    built_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    checked_at TIMESTAMPTZ NOT NULL DEFAULT now()   -- when EDGAR was last checked for newer filings
);

CREATE INDEX companies_last_viewed_idx ON companies (last_viewed_at NULLS FIRST) WHERE NOT is_showcase;
