-- Phase 4: what the model stages produced, once per filing (extraction) or per latest filing (synthesis).
-- analysis_runs holds the lock and token counts; this table holds the verified output the snapshot reads.

CREATE TABLE model_outputs (
    output_id BIGSERIAL PRIMARY KEY,
    company_id BIGINT NOT NULL REFERENCES companies ON DELETE CASCADE,
    filing_id BIGINT NOT NULL REFERENCES filings ON DELETE CASCADE,
    stage TEXT NOT NULL,                  -- extract (the filing read) | synthesize (the latest filing it covers)
    pipeline_version INTEGER NOT NULL,
    model TEXT NOT NULL,
    input_chars INTEGER NOT NULL,
    output JSONB NOT NULL,                -- items with verification, references resolved to stable descriptions
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (filing_id, stage, pipeline_version)
);
CREATE INDEX model_outputs_company_idx ON model_outputs (company_id, stage);
