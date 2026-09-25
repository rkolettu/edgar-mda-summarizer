"""Reads and writes the research store."""

from __future__ import annotations

from datetime import date

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from research.adapters import DocRef
from research.extract import Extraction, FactRecord, SectionRecord

STALE_RUN_MINUTES = 15
# Section text is kept for the filings comparisons read (latest two annual, latest two interim); older filings keep
# their facts and section fingerprints. Keeps a company near 2-4 MB so the free 0.5 GB Neon tier holds ~100 companies.
KEEP_ANNUAL_TEXT = 2
KEEP_INTERIM_TEXT = 2


def _insert_returning(conn: psycopg.Connection, sql: str, rows: list[tuple]) -> list[int]:
    if not rows:
        return []
    with conn.cursor() as cur:
        cur.executemany(sql, rows, returning=True)
        ids = []
        while True:
            ids.append(cur.fetchone()[0])
            if not cur.nextset():
                break
    return ids


def upsert_company(conn: psycopg.Connection, cik: int, ticker: str | None, name: str | None, showcase: bool = False) -> int:
    return conn.execute(
        """
        INSERT INTO companies (cik, ticker, name, is_showcase) VALUES (%s, %s, %s, %s)
        ON CONFLICT (cik) DO UPDATE SET
            ticker = COALESCE(EXCLUDED.ticker, companies.ticker),
            name = COALESCE(EXCLUDED.name, companies.name),
            is_showcase = companies.is_showcase OR EXCLUDED.is_showcase,
            updated_at = now()
        RETURNING company_id
        """,
        (cik, ticker, name, showcase),
    ).fetchone()[0]


def refresh_company_profile(conn: psycopg.Connection, company_id: int) -> None:
    """Currency, standard and fiscal year end follow the company's latest original filing."""
    conn.execute(
        """
        UPDATE companies c SET
            reporting_currency = COALESCE(latest.reporting_currency, c.reporting_currency),
            accounting_standard = COALESCE(latest.accounting_standard, c.accounting_standard),
            fiscal_year_end = COALESCE(latest.fiscal_year_end, c.fiscal_year_end),
            updated_at = now()
        FROM (
            SELECT reporting_currency, accounting_standard, fiscal_year_end
            FROM filings WHERE company_id = %s AND NOT is_amendment
            ORDER BY period_end DESC NULLS LAST, filing_date DESC LIMIT 1
        ) latest
        WHERE c.company_id = %s
        """,
        (company_id, company_id),
    )


def parsed_version(conn: psycopg.Connection, accession: str) -> int | None:
    row = conn.execute("SELECT parser_version FROM filings WHERE accession_number = %s", (accession,)).fetchone()
    return row[0] if row else None


def claim_stage(conn: psycopg.Connection, accession: str, stage: str, version: int, force: bool = False) -> int | None:
    """Starts a stage unless another worker is running it or it already succeeded at this version (unless forced)."""
    with conn.transaction():
        conn.execute(
            """
            UPDATE analysis_runs SET status = 'failed', error = 'abandoned', finished_at = now()
            WHERE accession_number = %s AND stage = %s AND pipeline_version = %s AND status = 'running'
              AND started_at < now() - make_interval(mins => %s)
            """,
            (accession, stage, version, STALE_RUN_MINUTES),
        )
        if force:
            conn.execute(
                "UPDATE analysis_runs SET status = 'superseded' WHERE accession_number = %s AND stage = %s "
                "AND pipeline_version = %s AND status = 'succeeded'",
                (accession, stage, version),
            )
        row = conn.execute(
            """
            INSERT INTO analysis_runs (accession_number, stage, pipeline_version, status) VALUES (%s, %s, %s, 'running')
            ON CONFLICT (accession_number, stage, pipeline_version) WHERE status IN ('running', 'succeeded') DO NOTHING
            RETURNING run_id
            """,
            (accession, stage, version),
        ).fetchone()
    return row[0] if row else None


def finish_stage(conn: psycopg.Connection, run_id: int, status: str, *, filing_id: int | None = None, error: str | None = None,
                 model: str | None = None, input_tokens: int | None = None, output_tokens: int | None = None) -> None:
    conn.execute(
        """
        UPDATE analysis_runs SET status = %s, filing_id = COALESCE(%s, filing_id), error = %s, model = %s,
            input_tokens = %s, output_tokens = %s, finished_at = now()
        WHERE run_id = %s
        """,
        (status, filing_id, error, model, input_tokens, output_tokens, run_id),
    )


def save_filing(conn: psycopg.Connection, company_id: int, filing: dict, source_url: str, documents: list[DocRef],
                extraction: Extraction, version: int) -> int:
    """Writes one parsed filing atomically. A re-parse replaces its facts and sections but keeps its filing_id."""
    meta = extraction.meta
    values = (
        company_id, meta.form_type, meta.base_form, meta.is_amendment, date.fromisoformat(filing["filing_date"]),
        date.fromisoformat(filing["report_date"]) if filing.get("report_date") else None,
        meta.period_start, meta.period_end, meta.fiscal_year, meta.fiscal_period, meta.period_months, meta.is_annual,
        meta.is_interim, meta.accounting_standard, meta.reporting_currency, meta.fiscal_year_end, source_url,
        Jsonb([{"url": d.url, "type": d.type, "role": d.role, "ixbrl": d.ixbrl} for d in documents]),
        version, extraction.parser_confidence, extraction.confidence_level, Jsonb(extraction.coverage),
        Jsonb(extraction.warnings),
    )
    with conn.transaction():
        existing = conn.execute(
            "SELECT filing_id FROM filings WHERE accession_number = %s FOR UPDATE", (filing["accession_number"],)
        ).fetchone()
        if existing:
            filing_id = existing[0]
            conn.execute(
                """
                UPDATE filings SET company_id = %s, form_type = %s, base_form = %s, is_amendment = %s, filing_date = %s,
                    report_date = %s, period_start = %s, period_end = %s, fiscal_year = %s, fiscal_period = %s,
                    period_months = %s, is_annual = %s, is_interim = %s, accounting_standard = %s, reporting_currency = %s,
                    fiscal_year_end = %s, source_url = %s, documents = %s, parser_version = %s, parser_confidence = %s, confidence_level = %s,
                    coverage = %s, warnings = %s, status = 'parsed', updated_at = now()
                WHERE filing_id = %s
                """,
                (*values, filing_id),
            )
            conn.execute("DELETE FROM facts WHERE filing_id = %s", (filing_id,))
            conn.execute("DELETE FROM filing_sections WHERE filing_id = %s", (filing_id,))
        else:
            filing_id = conn.execute(
                """
                INSERT INTO filings (company_id, form_type, base_form, is_amendment, filing_date, report_date, period_start,
                    period_end, fiscal_year, fiscal_period, period_months, is_annual, is_interim, accounting_standard,
                    reporting_currency, fiscal_year_end, source_url, documents, parser_version, parser_confidence,
                    confidence_level, coverage, warnings, accession_number)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING filing_id
                """,
                (*values, filing["accession_number"]),
            ).fetchone()[0]
        sections = _save_sections(conn, filing_id, extraction.sections)
        _save_facts(conn, company_id, filing_id, extraction.facts, sections, version)
        if meta.is_amendment:
            _link_amendment(conn, filing_id)
    return filing_id


def _save_sections(conn: psycopg.Connection, filing_id: int, sections: list[SectionRecord]) -> dict[str, tuple[int, str]]:
    ids = _insert_returning(
        conn,
        """
        INSERT INTO filing_sections (filing_id, category, source_kind, source_label, heading, document_url, element_id,
            ordinal, char_count, text_hash, text, confidence)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING section_id
        """,
        [
            (filing_id, s.category, s.source_kind, s.source_label, s.heading, s.document_url, s.element_id, s.ordinal,
             s.char_count, s.text_hash, s.text, s.confidence)
            for s in sections
        ],
    )
    by_ref = {s.ref: (section_id, s.category) for s, section_id in zip(sections, ids, strict=True)}
    parents = [(by_ref[s.parent_ref][0], by_ref[s.ref][0]) for s in sections if s.parent_ref in by_ref]
    if parents:
        with conn.cursor() as cur:
            cur.executemany("UPDATE filing_sections SET parent_section_id = %s WHERE section_id = %s", parents)
    return by_ref


def _save_facts(conn: psycopg.Connection, company_id: int, filing_id: int, facts: list[FactRecord],
                sections: dict[str, tuple[int, str]], version: int) -> None:
    ids = _insert_returning(
        conn,
        """
        INSERT INTO facts (company_id, filing_id, fact_key, fact_type, category, subcategory, canonical_metric, label,
            reported_label, xbrl_concept, dimensions, dimensions_hash, value_reported, reported_scale, reported_unit,
            reported_currency, value_normalized, normalized_unit, currency, decimals, accounting_standard, text_value,
            period_type, period_start, period_end, fiscal_year, fiscal_period, period_months, is_comparative,
            extraction_method, parser_confidence, confidence_level, pipeline_version)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING fact_id
        """,
        [
            (company_id, filing_id, f.fact_key, f.fact_type, f.category, f.subcategory, f.canonical_metric, f.label,
             f.reported_label, f.xbrl_concept, Jsonb(f.dimensions), f.dimensions_hash, f.value_reported, f.reported_scale,
             f.reported_unit, f.reported_currency, f.value_normalized, f.normalized_unit, f.currency, f.decimals,
             f.accounting_standard, f.text_value, f.period_type, f.period_start, f.period_end, f.fiscal_year,
             f.fiscal_period, f.period_months, f.is_comparative, f.extraction_method, f.parser_confidence,
             f.confidence_level, version)
            for f in facts
        ],
    )
    sources = []
    for fact, fact_id in zip(facts, ids, strict=True):
        for s in fact.sources:
            section_id, category = sections.get(s.section_ref or "", (None, None))
            sources.append((fact_id, filing_id, section_id, category, s.heading, s.table_label, s.source_text,
                            s.document_url, s.xbrl_element_id))
    if sources:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO fact_sources (fact_id, filing_id, section_id, category, heading, table_label, source_text,
                    document_url, xbrl_element_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                sources,
            )


def _link_amendment(conn: psycopg.Connection, filing_id: int) -> None:
    conn.execute(
        """
        UPDATE filings a SET amends_filing_id = (
            SELECT o.filing_id FROM filings o
            WHERE o.company_id = a.company_id AND o.base_form = a.base_form AND NOT o.is_amendment
              AND o.period_end = a.period_end
            ORDER BY o.filing_date DESC LIMIT 1)
        WHERE a.filing_id = %s
        """,
        (filing_id,),
    )


def prune_section_text(conn: psycopg.Connection, company_id: int) -> int:
    """Drops section text outside the retention window; facts, hashes and sources stay."""
    return conn.execute(
        """
        UPDATE filing_sections s SET text = NULL
        FROM filings f
        WHERE s.filing_id = f.filing_id AND f.company_id = %(company)s AND s.text IS NOT NULL
          AND f.filing_id NOT IN (
              (SELECT filing_id FROM filings WHERE company_id = %(company)s AND is_annual AND NOT is_amendment
               ORDER BY period_end DESC NULLS LAST LIMIT %(annual)s)
              UNION ALL
              (SELECT filing_id FROM filings WHERE company_id = %(company)s AND is_interim AND NOT is_amendment
               ORDER BY period_end DESC NULLS LAST LIMIT %(interim)s))
        """,
        {"company": company_id, "annual": KEEP_ANNUAL_TEXT, "interim": KEEP_INTERIM_TEXT},
    ).rowcount


def storage_bytes(conn: psycopg.Connection) -> int:
    return conn.execute("SELECT pg_database_size(current_database())").fetchone()[0]


# --- reads for the API ---

HEADLINE_METRICS = ("revenue", "gross_profit", "operating_income", "net_income", "eps_diluted", "operating_cash_flow",
                    "capex", "cash", "total_assets", "long_term_debt")


def find_company(conn: psycopg.Connection, ticker: str | None = None, cik: int | None = None) -> dict | None:
    column, key = ("cik", cik) if cik is not None else ("ticker", (ticker or "").strip().upper().replace(".", "-"))
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            "SELECT company_id, cik, ticker, name, reporting_currency, accounting_standard, fiscal_year_end "
            f"FROM companies WHERE {column} = %s",
            (key,),
        ).fetchone()


def company_filings(conn: psycopg.Connection, company_id: int) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            """
            SELECT f.filing_id, f.accession_number, f.form_type, f.filing_date, f.period_start, f.period_end,
                f.fiscal_year, f.fiscal_period, f.is_annual, f.accounting_standard, f.reporting_currency,
                f.parser_confidence, f.confidence_level, f.coverage, f.warnings, f.source_url,
                (SELECT count(*) FROM facts WHERE filing_id = f.filing_id) AS fact_count
            FROM filings f WHERE f.company_id = %s
            ORDER BY f.period_end DESC NULLS LAST, f.filing_date DESC
            """,
            (company_id,),
        ).fetchall()


def current_metrics(conn: psycopg.Connection, filing_id: int) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            """
            SELECT canonical_metric AS metric, label, reported_label, value_normalized AS value, currency,
                normalized_unit AS unit, period_start, period_end, fiscal_year, fiscal_period, period_months,
                xbrl_concept, confidence_level AS confidence
            FROM facts
            WHERE filing_id = %s AND NOT is_comparative AND canonical_metric = ANY(%s)
            ORDER BY canonical_metric, period_months NULLS FIRST
            """,
            (filing_id, list(HEADLINE_METRICS)),
        ).fetchall()
    # NUMERIC arrives as Decimal; the API speaks floats.
    return [{**row, "value": float(row["value"]) if row["value"] is not None else None} for row in rows]
