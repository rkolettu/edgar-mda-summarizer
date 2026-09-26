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
   re-fetched. Measured after phase 2 (with disclosure families): 20 filings for 4 companies take 6.2 MB, about
   1.5-2.5 MB per company. Past 100 non-showcase companies the least recently viewed are evicted (counting companies,
   because Postgres reuses freed space but never shrinks the file, so file size cannot drive eviction), and new
   companies are refused above 450 MB of physical size.
3. **Ingestion.** Showcase companies (`backend/research/watchlist.txt`) are kept current by a daily GitHub Actions job
   (`.github/workflows/ingest.yml`; free for public repositories, no Vercel time limit), so their pages load instantly.
   Any other ticker is ingested on demand by `GET /api/research/{ticker}`: deterministic parsing of about ten filings
   takes 15-60 seconds and fits the Vercel Hobby 5-minute function limit; later requests read the stored snapshot
   (about 30 ms) and EDGAR is rechecked at most daily. A second request for a company already being parsed waits for
   the first instead of building a partial snapshot. Model stages (phase 4) are saved per stage, so a timeout
   resumes rather than restarts. The page shows the stored tabs as soon as they arrive; if the model quota is spent,
   those tabs still render and the Overview says the summary is unavailable.
4. **Model: stay on the Gemini free tier.** Google no longer publishes fixed free limits (see AI Studio for the
   project's own); recent reports put Flash-Lite near 500 requests/day and Flash near 20/day, and 2.5 models are now
   limited to projects that already use them. Extraction runs on `gemini-3.5-flash-lite` and synthesis on
   `gemini-3.8-flash` (the current stable models; `GEMINI_EXTRACT_MODEL` and `GEMINI_SYNTH_MODEL` override them). A
   spent quota, a model the project cannot use, an overloaded model or malformed output moves to the next model:
   the stage's own, then `GEMINI_MODEL` (the legacy summary's model, which an existing project can use), then the other
   stage's, then Mistral's free tier if `MISTRAL_API_KEY` is set. Groq's free tier caps tokens per minute too low for
   the extraction call; Cerebras now requires a card; most OpenRouter free models were withdrawn.
5. **One snapshot payload per company** with every tab; source text loads on click.

## Schema (migrations 001-004)

| Table | Holds |
|---|---|
| `companies` | CIK, ticker, name, reporting currency, accounting standard, fiscal year end, showcase flag, last viewed |
| `filings` | Generic filing model: form as filed, base form, amendment link, period, fiscal year and period, annual/interim, standard, currency, documents, parser version, confidence, coverage, warnings |
| `filing_sections` | Semantic category, how it was found (XBRL text block, heading, exhibit), heading, text hash, text (retention-pruned), parent section |
| `facts` | Stable `fact_key` (e.g. `metric.revenue`), canonical metric, reported label, XBRL concept, dimensions, reported and normalized value, unit, scale, currency, period and fiscal labels, comparative flag, extraction method, confidence; columns for disclosure status and materiality filled by later phases |
| `fact_sources` | Where each fact appears: document, element id, table row or sentence, section |
| `analysis_runs` | One row per stage per filing: tokens, model, status; a unique partial index doubles as a lock so concurrent requests never pay twice |
| `member_aliases` | A company renamed a category between filings: old key, new key, how it was linked, evidence |
| `research_snapshots` | One JSON payload per company with every tab's data, its versions, and when EDGAR was last checked |
| `filing_changes` | Every new, changed or removed item in the latest filing (numbers, derived ratios, wording): values and bases, change, comparison, triggers, flags, materiality score with components and reasons, tier, source ids |
| `model_outputs` | What each model stage produced, once per filing (extraction) or per latest filing (synthesis): verified items with their quotes, figure checks and references resolved to stable descriptions; `analysis_runs` holds the lock and token counts |

Comparisons are recomputed in code whenever the snapshot is rebuilt (they are cheap) and stored in `filing_changes`,
which also serves as the candidate list for the later model stages; the facts compared get their `disclosure_status`
and `materiality_score`.

Derived metrics (margins, growth, free cash flow, cash conversion, net cash, receivable and inventory days, discrete
quarters from year-to-date totals) are computed in `research/metrics.py` when the snapshot is built, never stored as
facts and never produced by a model; a restated period takes the latest filing's value.

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

`research/materiality.py`: `score = .35 magnitude + .25 change + .20 strategic + .10 language + .10 novelty`, plus
bonuses (subsequent event, new guarantee or financing, hypothetical-to-realized language, material weakness, critical
audit matter, over $10B), capped at 1.0. Every score keeps its components and plain-language reasons.

- Magnitude is relative to the company's own latest fiscal-year revenue (5% scores 0.7), operating income (10%,
  floored at 2% of revenue) and total assets (10%); the $10B trigger applies only to USD reporters because amounts
  are never converted. Balances (commitments, guarantees, debt) are sized by their level; statement lines and amounts
  over a period (revenue by segment) by how much they moved, or every large line of a large company would rank as
  material every quarter.
- A percentage change needs an amount behind it (0.5% of revenue or $1B), so a doubling of a small line stays low.
  Ratios and derived metrics change in percentage points (5 points scores 0.7), day counts in days (15).
- Tiers: ≥ .70 most material, ≥ .45 notable, otherwise background (never sent to synthesis).

Checked on NVIDIA's Q2 FY2027 10-Q: the new $105B SB Energy guarantee scores 1.00; supply commitments at $279B
(+134%) 0.85; revenue +106% year over year 0.83; a new risk factor about export controls 0.50; a repeated risk factor
about 0.15.

## Comparisons (phase 3)

`research/changes.py` compares the latest filing with three bases: the **previous report**, the **latest annual
report**, and the **same period a year earlier**.

- **Balances** (commitments, guarantees, debt, headline balance sheet lines) compare with the previous report, with the
  annual value alongside (vs. the prior annual report when the latest filing is annual).
- **Amounts over a period** compare with the same period a year earlier: the discrete quarter when the filing reports
  one with a comparable, else the year to date.
- **Derived ratios** for the latest quarter or year (margins, capex intensity, tax rate, receivable and inventory
  days, non-operating share of pretax income) compare year over year. Receivables or inventory growing 20 points
  faster than revenue is its own item.
- **Status**: new (nothing earlier, not even a comparative, and an earlier filing exists that could have reported it),
  changed (5% or more, one point for ratios), repeated, or removed. Interim filings are condensed, so a line missing
  from a 10-Q is removed only when the previous report was also a 10-Q. A removed line is marked "possibly renamed or
  split" when the same filing adds lines under the same concept or with a similar name.
- Keys stay stable across renames through `member_aliases`: **comparative-period bridging** (NVIDIA renamed its
  supply-commitment category between Q1 and Q2, but the Q2 filing reports April's $119B under the new name) and
  dropped-word matching.
- **Anonymized customers** ("Customer A") are relabeled by companies every period, so their shares are compared as a
  set: the largest share and how many are disclosed.
- Three or more new lines under a concept the company never tagged before are a table **itemized for the first
  time** (TSMC's 20-F began tagging each bond in FY2025), folded into one entry and scored below a genuinely new item.

**Wording** (`research/narrative.py`) is compared sentence by sentence with two fingerprints, exact and with numbers
and dates masked, so "fiscal 2025" → "fiscal 2026" and "As of April 26" → "As of July 26" are repeats and "$119
billion" → "$279 billion" is a number change. Unmatched sentences that share most of their words (Jaccard ≥ 0.75)
are rewordings; the rest form new or removed passages. Flattened table rows are left out. A 10-Q's risk factors list
only updates, so they compare with the annual report without looking for removals, and language the previous 10-Q
already added is marked "first disclosed in Q1". Management discussion is rewritten every period, so only sentences
with trigger phrases (weighted lower when hypothetical: "could", "may", "if") are candidates. Amounts quoted in a
passage size it, except in risk factors.

**Grouping**: a tagged value, the note sentence and the MD&A sentence about the same amount are shown as one item,
led by the tagged value. Amounts must match within 0.5%, and the wording must name the value's subject (a shared
distinctive word stem), since round amounts often coincide ($25B of leases vs. a $25B commercial paper program).

## Model stages (phase 4)

`research/interpret.py`, two calls, each run once and stored in `model_outputs`:

- **A, extraction** (Flash-Lite, once per filing, for the latest annual report and the latest interim report): reads
  the business description (10-K Item 1, 20-F Item 4), management's discussion without its tables, and risk
  factors: for an annual report an outline of its risk headings plus the passages that are new or changed since the
  previous annual report (new ones and flagged language first); for a 10-Q its risk factor updates in full. It returns
  the business summary, segments, strategy, what moved the results (up, down, mixed), outlook, management's
  opportunities and cautions, company-specific risks (new, heightened or ongoing; has happened or could happen) and
  explanations of non-operating items. Every item quotes one sentence verbatim; the quote is checked against the text
  sent, and each figure against that text and the filing's tagged values. Items whose quote is not found are kept
  but hidden until the reader asks for them.
- **B, synthesis** (Flash, once per latest filing): never sees a filing. It reads what code computed (financial
  tables, the ranked filing changes, the earnings bridge) and A's verified items, each under an id (`m.revenue`,
  `c3`, `r2`), and returns key takeaways, a business overview, ranked risks, a neutral earnings quality summary and
  a "why it matters" note for top filing changes. Statements must cite ids; those citing none it was given are
  dropped, and every number must appear in its input (untraced figures are underlined for the reader). References
  are stored as stable descriptions, not row ids, because `filing_changes` rows are recreated on each rebuild.

The page loads the stored snapshot first; when its analysis is missing it calls `POST /api/research/{ticker}/insights`,
which runs the missing stages (A for both filings in parallel, then B) under the `analysis_runs` lock, rebuilds the
snapshot and returns it. A second request for the same company waits for the first. After a spent quota, requests
for that company do not retry the models for 30 minutes; the tabs built from the filings keep working. The daily
workflow passes `--interpret` when a model key is set, so showcase companies have their analysis ready.

Measured input sizes (characters / 4 as tokens), live filings:

| Company | Call A, annual | Call A, latest 10-Q | Call B (before A's items) |
|---|---|---|---|
| NVIDIA | 84k chars, ~21k tokens (10-K) | 53k chars, ~13k tokens | ~1.5k tokens |
| Microsoft | 92k chars, ~23k tokens (10-K) | none newer than the 10-K | ~1.5k tokens |
| TSMC | 77k chars, ~19k tokens (20-F) | not filed (6-K) | ~1.7k tokens |
| Suncor | 45k chars, ~11k tokens (40-F: MD&A only) | not filed (6-K) | ~1.3k tokens |

With A's items added, B is roughly 4-6k tokens, so a company's first analysis costs about 40k input tokens in three
calls (the legacy summary: about 99k per cache miss, repeated whenever any of its three filings changed), and a new
10-Q costs one A call and one B call. Tab views cost nothing.

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
| 2 Deterministic facts | Disclosure families (commitments, guarantees, debt, investments, capital return, non-operating and unusual items, customer concentration, backlog, taxes) and segment, geographic and product revenue; renamed-category linking; derived metrics and working capital; 5-year history from three annual reports; snapshot builder; on-demand `GET /api/research/{ticker}` with storage guard; tab frame, Financials tab, Capital & Commitments tab | **Done** |
| 3 Compare and score | Comparison engine (previous report, annual report, year earlier), disclosure status, sentence fingerprints and narrative diffs, trigger phrases with modality, materiality scoring, grouping, `filing_changes`; Filing Changes tab | **Done** |
| 4 Interpretation | Calls A and B, insights bound to fact ids, verification; Overview, Business & Strategy, Risks, Earnings Quality | **Done** |
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

## Phase 2 findings

Live runs on NVIDIA, Microsoft, TSMC and Suncor, all from tags, with no model:

- NVIDIA's supply and capacity commitments read $95.2B (FY26 10-K), $119B (Q1) and $279B (Q2), although NVIDIA renamed
  the category between Q1 and Q2: the Q2 filing repeats April's $119B under the new name, which links the two.
  "Multi-year cloud service agreement commitments" became "Cloud service agreement commitments" with no repeated
  value; names that differ only by dropped qualifiers, with amounts in a plausible range, are linked too. A generic
  match ("Other commitments" inside "Future purchase and other commitments") is rejected. The $105B SB Energy
  guarantee shows as new, and its post-quarter value as a subsequent event.
- Microsoft tags $329.1B of data center leases not yet commenced (twice, as finance and operating leases, from one
  sentence; merged into one item) and a $13B equity-method funding commitment; Microsoft's own product renames
  (Gaming to Xbox) link through repeated values.
- TSMC tags US dollar convenience translations beside its NT dollar amounts; the reporting currency wins.
- NVIDIA moved marketable securities from a standard tag to its own tag and then split it in two; a company tag whose
  statement row reads exactly like a metric maps at medium confidence, and net cash is left blank rather than shown
  understated when a component the company normally reports is missing.
- Not linked yet (left for the phase 5 model mapping): NVIDIA's "Operating lease not yet commenced" and "Data center
  lease not yet commenced" share no distinctive words; customers are anonymized and relabeled between filings.
- The chart palette's orange and teal failed the dataviz validator's color-vision check (protan delta E 5.6); both were
  resaturated within their hues and now pass.

## Phase 3 findings

Live runs on NVIDIA (10-Q), Microsoft (10-K), TSMC (20-F) and Suncor (40-F), with no model:

- NVIDIA Q2 FY2027: 31 most material, 50 notable. Top: the $105B SB Energy guarantee (new, subsequent event) with the
  note's wording folded in; guarantees' maximum exposure $0.86B → $108.5B; new commitment lines (AI cloud partnership
  $36B, data center leases not yet commenced $25B and $20B); supply commitments $119B → $279B; debt issued $24.9B from
  zero with the "In June 2026, we issued $25.0 billion" sentence. Language: new export control and indebtedness risk
  factors, the new "Commitments, guarantees, and other commercial arrangements" risk. The largest customer's share of
  receivables fell from 30% to 22% while five customers are now disclosed, up from three.
- Microsoft FY2026 10-K: leases not yet commenced $92.7B → $329.1B, capex +80%, capex intensity +12 points,
  remaining performance obligations $375B → $684B, inventory growing 31 points faster than revenue.
- TSMC FY2025 20-F: nothing above 0.70 (growth of 30-47% is notable for a company this size); its first per-bond
  tagging (18 US dollar bonds) folds into one first-itemized entry instead of 18 "new" bonds.
- Suncor FY2025 40-F: the syndicated credit facility extended from 2027 to 2029 shows as a new 2029 facility with the
  2027 one "possibly renamed or split into" it.
- Fixed along the way: sentences split after "U.S." and "Inc."; table rows without a period glued onto the following
  sentence (hiding NVIDIA's new $25B notes issuance); a trailing comma kept years from counting as rolled forward;
  grouping on amount alone folded unrelated round numbers together; a CSS rule outside Tailwind's layers overrode every
  button's text size.
- Not solved yet: passages of consecutive new risk-factor sentences can run two risk factors together (no headings in
  the extracted text); NVIDIA's renamed lease line is still new plus removed (marked as possibly renamed); coverage
  gaps from phase 1 (Microsoft's 10-K risk factors, JPMorgan's 10-Q MD&A, ASML's 20-F narrative) leave those diffs
  empty. Storage after vacuum: about 1.6 MB per company in total, of which about 120 KB is `filing_changes`.

## Phase 4 findings

- Narrative sections now keep paragraphs and table rows as lines (a context flag on `sec.html_to_text`, so the
  legacy summary still reads one line). Section boundaries on NVIDIA, Apple, Amazon, JPMorgan, Microsoft and TSMC
  filings are unchanged; the lines give risk factor headings (the outline for call A), let flattened table rows be
  dropped from prose, and end sentences after a table row.
- Microsoft splits words inside its headings ("ITEM 1A. RIS K FACTORS", "B USINESS"); tolerating that recovers its
  10-K risk factors (80k characters) and business section, a phase 1 coverage gap, for the legacy summary too.
- Running page headers ("13 / PART I / Item 1A") sit between the halves of a sentence at page breaks; they are
  removed before wrapped lines are joined.
- The model stages were exercised end to end on the stored filings with a stand-in model (no model key in this
  environment): quotes copied from the real inputs verify, numbers copied from call B's input trace, and a quote the
  model invents is hidden. Live Gemini output quality is not yet measured; the first run with a real key is the check.
- Whether a server can write the analysis depends on where it runs (the daily job and the web app hold their own
  keys), so the snapshot's `configured` flag is set when it is served.
- The page no longer calls the legacy `/api/summarize` for a company the research store can serve; it remains the
  fallback when the store is not configured or cannot read a company's filings (retired in phase 6).

## Operating it

```bash
cd backend
DATABASE_URL=postgres://... SEC_USER_AGENT="App name contact@email" python -m research.ingest NVDA TSM SU
python -m research.ingest --watchlist          # showcase companies
python -m research.ingest NVDA --force         # re-parse at the current parser version
```

`GET /api/research/{ticker}` returns a company's snapshot (ingesting it on first request); `GET
/api/research/{ticker}/filings` lists stored filings with their coverage.

The scheduled workflow needs repository secrets `DATABASE_URL` and `SEC_USER_AGENT`; until they exist it skips with
a notice. GitHub pauses scheduled workflows in public repositories after 60 days without commits; re-enable it from
the Actions tab if that happens.
