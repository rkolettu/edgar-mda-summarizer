# SEC filing research

Pulls the latest annual 10-K, 20-F, or 40-F for a ticker from SEC EDGAR, isolates management's discussion, and uses Gemini 2.5 Flash to summarize revenue drivers, capital allocation, and macro risks.

- `backend/`: FastAPI app serving `GET /api/summarize?ticker=AAPL` (accepts a ticker or company name) and `GET /api/search?q=apple` (autocomplete)
- `frontend/`: React + Vite + Tailwind CSS v4

## What it produces

- For 10-Ks, summary tiles and 5-year revenue, free cash flow and margin trends from the SEC's structured XBRL data (`data.sec.gov` companyfacts)
- An AI-assisted research memo from the 10-K's Item 7 MD&A (or Exhibit 13), a 20-F operating review, or a 40-F management discussion exhibit, with each insight's source quote checked against the filing
- Revenue segments reconciled against reported revenue, and capital deployment from the cash flow statement
- What changed versus the prior year's filing of the same form, when available
- For 10-Ks, a latest-quarter update from the most recent 10-Q filed after the 10-K
- Every completed analysis saved to Postgres when `DATABASE_URL` is set (SQLite otherwise), so repeat searches for a filing skip Gemini; `/api/cache/stats` shows how many companies are stored

Foreign issuer filing layouts vary. The app recognizes embedded operating reviews in 20-Fs and referenced management discussion exhibits in 40-Fs; when it cannot verify the section, it returns an error rather than summarizing unrelated material. XBRL trend cards are currently limited to 10-Ks. The app detects each foreign filing's reporting currency, labels amounts in it, and omits the charts when it is not US dollars, because their schema assumes US dollars. When a 20-F is only a cross-reference index into an integrated annual report, the app reads the annual report's own review chapter, in the document or its exhibit (for example Unilever, Vale, Santander and AstraZeneca); some such reports (for example Shell, BP and HSBC) are not yet supported. This app does not yet analyze foreign issuers' 6-K interim filings.

How the AI analysis is checked:

- Gemini receives the company's SEC XBRL figures (revenue, margins, cash flows, buybacks, EPS, latest quarter) and is told to use those exact values and not to calculate new ones. Quarterly figures are generally unaudited. It runs at temperature 0.
- Every insight must quote one sentence from the filing. The quote is matched against the filing text.
- Every dollar amount and percentage in an insight's headline and paragraph is checked for a numerical match in the filing text (including tables with a nearby stated scale) or XBRL data, including recent margins and growth rates derived from it.
- Insights whose quote is not found are hidden by default. Figures that could not be traced are underlined.

These checks confirm that the quote appears in the source and that the numerical values appear somewhere in the filing or XBRL data. They do not prove a value belongs to the claimed metric or period, or that the AI used it in the right context. Review the original filings before using the output in an investment decision.

## Research store (in progress)

A new pipeline parses each filing once into Postgres (structured facts from the filing's inline XBRL, note sections,
sources and coverage) so several research tabs can render without rereading filings or calling a model per view. See
[docs/research-architecture.md](docs/research-architecture.md) for the design and phase plan.

- `python -m research.ingest NVDA TSM` (from `backend/`, with `DATABASE_URL` and `SEC_USER_AGENT` set) parses a
  company's recent filings; `--watchlist` ingests the showcase companies in `backend/research/watchlist.txt`. No model
  calls.
- `.github/workflows/ingest.yml` runs the watchlist daily once the `DATABASE_URL` and `SEC_USER_AGENT` repository
  secrets are set.
- `GET /api/research/{ticker}` returns the company's research snapshot (every tab's data), parsing its filings on
  the first request; every tab reads it. Financials, Capital & Commitments and Filing Changes are built from the
  filings in code (Filing Changes ranks what the latest filing adds, changes or drops, numbers and wording, with a
  materiality score); Overview, Business & Strategy, Risks and Earnings Quality add an AI analysis that is written
  once per filing, quotes the filing for every extracted item, and cites the stored facts for every summary point. An
  omission check then lists everything material code flagged (top filing changes, subsequent events, new guarantees,
  serious filing language) and shows whether the summary covers each item, what it added, and why the rest was left out.
- `POST /api/research/{ticker}/insights` writes that analysis when it is missing (Gemini free tier: Flash-Lite reads
  the filing text, Flash writes the summary from stored facts; Mistral's free tier is an optional fallback). The
  legacy `/api/summarize` is used only when the research store cannot serve a company.
- `POST /api/research/{ticker}/chat` answers questions about a company's stored filings ("Ask about this filing" on
  the page). Each question is answered from the key figures and the filing passages that best match it, and the
  answer cites the passages. It runs on Groq's free tier (`GROQ_API_KEY`) with Mistral's as the fallback, never on
  Gemini. `GET /api/research/{ticker}/filings` lists the stored filings and their coverage.
- `GEMINI_EXTRACT_MODEL` and `GEMINI_SYNTH_MODEL` override the research models (defaults `gemini-3.5-flash-lite` and
  `gemini-3.8-flash`); `GEMINI_MODEL` is the legacy summary's model and the research stages' first fallback (Google
  now limits 2.5 models to projects that already use them). `MISTRAL_API_KEY` enables the last-resort fallback.

## Tests

```bash
cd backend
pip install -r requirements-dev.txt
python -m pytest
```

The suite runs offline against a fake SEC and a fake Gemini client.

## Run locally

Backend (terminal 1):

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export GEMINI_API_KEY="your-key-here"
export SEC_USER_AGENT="Your Name Research (you@example.com)"
uvicorn main:app --reload --port 8000
```

Frontend (terminal 2):

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173.

The backend reads variables from its process environment. `backend/.env.example` lists the required names; use your own contact email for SEC requests and keep real keys out of Git.
