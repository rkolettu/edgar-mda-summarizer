# Research pipeline architecture

**Analyze once → store structured facts in Postgres → render many tabs.**

The company research page is moving from "summarize MD&A on every cache miss" to a pipeline that parses each filing
once, stores structured facts with their sources, computes comparisons and materiality in code, and uses the LLM only
where interpretation adds value. Tabs read a stored snapshot; switching tabs never calls a model.

```
SEC filing ─► adapter: locate documents (primary, tagged exhibits, MD&A / annual-report exhibits)
          ─► Tier 1  inline XBRL: cover page, values (unit, scale, sign, period, dimensions), note text blocks
          ─► Tier 2  table parser for untagged tables                         (phase 2)
          ─► Tier 3  sections: note text blocks by concept + adapter headings (MD&A, risk factors)
          ─► Tier 4  full-text concept search when an expected category is missing  (phase 5)
          ─► Tier 5  LLM classification of what tiers 1-4 cannot place       (phase 5)
          ─► coverage report + parser confidence (nothing is dropped silently)
          ─► Postgres: filings, sections, facts, fact sources
          ─► comparisons + materiality (code)                                 (phase 3)
          ─► LLM: extraction on selected sections, synthesis, omission audit  (phases 4-5)
          ─► research snapshot (one JSON payload per company) ─► tabs
```

## Why inline XBRL is tier 1

Filings tag nearly every number inside the HTML we already download. The old pipeline flattened the HTML to text and
discarded the tags; the SEC companyfacts API it used omits every value broken out by category. For NVIDIA the tags
alone give, with no model:

| NVIDIA | FY26 10-K | Q1 FY27 10-Q | Q2 FY27 10-Q |
|---|---|---|---|
| Supply and capacity commitments | $95.2B | $119B | $279B |
| Guarantees (maximum exposure) | $3.5B | not reported | $108.5B, incl. a new $105B financial guarantee (also tagged as a subsequent event) |
| Long-term debt | $8.47B | $8.47B | $33.4B ($25B of notes issued) |
| Non-operating income | $11.1B (year) | $16.4B, incl. $13.4B unrealized equity gains | $7.8B |

Note text blocks are tagged by taxonomy concept (`us-gaap:CommitmentsAndContingenciesDisclosureTextBlock`,
`ifrs-full:DisclosureOfEventsAfterReportingPeriodExplanatory`), which gives note boundaries and semantic categories
without relying on note numbers or Item numbers. The same parser handles 10-K, 10-Q, 20-F (US GAAP or IFRS) and 40-F.

## Decisions

1. **Postgres only for the research store.** Tests run a real Postgres (`pgserver`); SQLite remains only for the
   legacy result cache.
2. **Storage (Neon free tier: 0.5 GB, 100 CU-hours/month, scales to zero after 5 minutes).** Store facts, fact
   sources, section fingerprints, and section text for the filings comparisons read (latest two annual, latest two
   interim); older text is pruned, facts stay. Never store raw HTML or unmapped XBRL: filings never change and can be
   re-fetched. Measured in phase 1: 36 filings for 8 companies used about 7 MB, roughly 0.9 MB per company. A storage
   guard (phase 2) evicts the least recently viewed non-showcase companies above about 400 MB.
3. **Ingestion.** Showcase companies (`backend/research/watchlist.txt`) are kept current by a daily GitHub Actions job
   (`.github/workflows/ingest.yml`; free for public repositories, no Vercel time limit), so their pages load instantly.
   Any other ticker is ingested on demand in the request (phase 2): deterministic parsing takes seconds and fits the
   Vercel Hobby 5-minute function limit; model stages are saved per stage, so a timeout resumes rather than restarts.
   If the model quota is spent, the deterministic tabs still render and narrative tabs say they are queued.
4. **Model: stay on the Gemini free tier.** Google no longer publishes fixed free limits (see AI Studio for the
   project's own); recent reports put Flash-Lite near 500 requests/day and Flash near 20/day, and 2.5 models are now
   limited to projects that already use them (`GEMINI_MODEL` overrides the model). Plan for phase 4: extraction on
   Flash-Lite, synthesis and audit on Flash, Mistral's free tier as an automatic fallback on quota errors. Groq's free
   tier caps tokens per minute too low for the extraction call; Cerebras now requires a card; most OpenRouter free
   models were withdrawn.
5. **One snapshot payload per company** with every tab; source text loads on click.

## Schema (migration 001)

| Table | Holds |
|---|---|
| `companies` | CIK, ticker, name, reporting currency, accounting standard, fiscal year end, showcase flag, last viewed |
| `filings` | Generic filing model: form as filed, base form, amendment link, period, fiscal year and period, annual/interim, standard, currency, documents, parser version, confidence, coverage, warnings |
| `filing_sections` | Semantic category, how it was found (XBRL text block, heading, exhibit), heading, text hash, text (retention-pruned), parent section |
| `facts` | Stable `fact_key` (e.g. `metric.revenue`), canonical metric, reported label, XBRL concept, dimensions, reported and normalized value, unit, scale, currency, period and fiscal labels, comparative flag, extraction method, confidence; columns for disclosure status and materiality filled by later phases |
| `fact_sources` | Where each fact appears: document, element id, table row or sentence, section |
| `analysis_runs` | One row per stage per filing: tokens, model, status; a unique partial index doubles as a lock so concurrent requests never pay twice |

Planned: `fact_comparisons` (sequential, vs annual, YoY deltas; recomputed when filings arrive), `member_aliases`
(company renames of XBRL categories), `candidates` (materiality triggers), `insights` (tab insights with fact and
source ids and verification), `research_snapshots`.

## Deterministic vs. model responsibilities

| Code (no tokens) | Model |
|---|---|
| Periods, units, scale, sign, currency, fiscal labels (52/53-week years) | Summarizing MD&A, business and strategy into qualitative facts |
| Mapping concepts to metrics (US GAAP and IFRS kept distinct where they differ) | Mapping a company-specific concept no rule or comparison bridges |
| Margins, growth, free cash flow, working capital, earnings bridge | Strategic importance; keeping management's upside and downside |
| Deltas, trends, new highs, thresholds; new/changed/repeated/removed | Explaining why a change matters |
| Materiality score, trigger phrases, deduplication | Confirming hypothetical-to-realized shifts in risk language |
| Quote and figure verification | Omission audit over stored candidates |

## Materiality (phase 3)

`score = .35 magnitude + .25 change + .20 strategic + .10 language + .10 novelty`, plus bonuses (subsequent event,
new guarantee or financing, critical audit matter, over $10B), capped at 1.0. Magnitude is relative to the company's
own revenue (5%), operating income (10%) and total assets (10%); the $10B absolute trigger applies only to USD
reporters because there is no FX conversion. Tiers: ≥ .70 top, ≥ .45 notable, otherwise background (never sent to
synthesis). Checked against NVIDIA: the new $105B guarantee scores ~1.0, supply commitments at $279B (+134%) ~0.85,
a word-for-word repeated risk factor ~0.15.

## Comparisons (phase 3)

Instants (commitments, debt, guarantees) compare with the previous filing, the latest annual and the same date a year
earlier; durations compare year over year for the same length (usually from the same filing's comparative) and
sequentially where 3-month data exists. Keys stay stable across filings through mapping rules, then
**comparative-period bridging**: NVIDIA renamed its supply-commitment category between Q1 and Q2, but the Q2 filing
reports the April figure ($119B) under the new name, which matches Q1's value under the old name, so code records the
alias. Interim filings are condensed, so a missing item is "removed" only when comparing like forms. Narrative
sections diff by paragraph hash and similarity, flagging changed numbers and "may" → "has" shifts.

## Token plan (phase 4-5)

Three calls per filing, once per filing: **A** extraction over MD&A, new or changed risk paragraphs, candidate note
blocks and a digest of stored numbers; **B** synthesis from stored facts, comparisons and candidates only; **C** audit
of candidates against the proposed insights. Measured baseline of the old pipeline: about 99k input tokens per cache
miss for NVIDIA, repeated whenever any of three filings changed. Estimate for the new one: 10-K about 30-45k, 10-Q about
20-35k, each once; tab views and history backfill cost nothing. A prompt change reruns only the affected stage.

## Filing-type adapters

`backend/research/adapters.py` is the only layer that knows form types. Each adapter declares its forms, the
categories a complete filing contains, and how to find narrative sections (reusing `sec.py`'s Item 7, 20-F operating
review, 40-F exhibit and annual-report rules). Documents come from the filing index, where EDGAR marks inline XBRL
documents; Suncor's 40-F keeps contexts in the primary document and facts in exhibit 99.2, and they are parsed as one
set. Amendments use their base form's adapter and expect nothing (a 10-K/A may be only Part III). Planned: 6-K
(untagged interim reports; text and table tiers) and 8-K (Item numbers map to fact types: 1.01 agreements, 2.01
acquisitions, 2.03 debt or guarantees, 2.05/2.06 restructuring or impairment, 4.02 restatements, 1.05 cyber incidents).

## Phases

| Phase | Scope | Status |
|---|---|---|
| 1 Foundation | Migrations; generic filing model; inline XBRL parser; metric mapping (US GAAP, IFRS); note sections; adapters for 10-K, 10-Q, 20-F, 40-F; ingest CLI and daily workflow; read-only `GET /api/research/{ticker}/filings`; token logging | **Done** |
| 2 Deterministic facts | Dimensional families (commitments, guarantees, debt, investments, capital return, non-operating, impairments, inventory charges, concentration, segments); alias bridging; derived metrics and working capital; 5-year history backfill; snapshot builder; on-demand ingestion with storage guard; tab frame, Financials tab, Capital & Commitments numbers | Next |
| 3 Compare and score | `fact_comparisons`, disclosure status, paragraph fingerprints and narrative diffs, trigger phrases, materiality; Filing Changes tab | |
| 4 Interpretation | Calls A and B, insights bound to fact ids, verification; Overview, Business & Strategy, Risks, Earnings Quality | |
| 5 Audit and robustness | Call C; full-text and model fallbacks; 6-K, 8-K; messy-filer regression set | |
| 6 Polish | Source drill-downs; retire `/api/summarize` and the `analyses` cache | |

## Phase 1 findings

Ingesting the watchlist (36 filings: NVDA, AAPL, MSFT, AMZN, JPM 10-K/10-Q; TSMC IFRS 20-F in TWD; ASML US GAAP
20-F in EUR; Suncor IFRS 40-F in CAD) succeeded for every filing in about two minutes. The coverage report surfaced
gaps in the existing narrative extractors, which also affect the current page:

- Microsoft 10-K risk factors, JPMorgan 10-Q MD&A, ASML 20-F operating review and risk factors, and Suncor's 2024
  MD&A are not isolated by the current heading rules. Suncor's risk factors live in its annual information form.
- Suncor's 40-F MD&A was never found because its cover sentence lists several exhibits at once; fixed by reading the
  exhibit index row first and verifying candidates in turn.
- IFRS revenue is not always the headline figure: Suncor tags gross revenues as `RevenueFromContractsWithCustomers`
  while it reports revenue net of royalties; the stored reported label ("Gross revenues") keeps that visible.

## Operating it

```bash
cd backend
DATABASE_URL=postgres://... SEC_USER_AGENT="App name contact@email" python -m research.ingest NVDA TSM SU
python -m research.ingest --watchlist          # showcase companies
python -m research.ingest NVDA --force         # re-parse at the current parser version
```

The scheduled workflow needs repository secrets `DATABASE_URL` and `SEC_USER_AGENT`; until they exist it skips with
a notice. GitHub pauses scheduled workflows in public repositories after 60 days without commits; re-enable it from
the Actions tab if that happens.
