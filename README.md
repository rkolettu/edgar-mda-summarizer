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

Foreign issuer filing layouts vary. The app recognizes embedded operating reviews in 20-Fs and referenced management discussion exhibits in 40-Fs; when it cannot verify the section, it returns an error rather than summarizing unrelated material. XBRL trend cards are currently limited to 10-Ks, and Canadian-dollar charts are omitted because their schema assumes US dollars. This app does not yet analyze foreign issuers' 6-K interim filings.

How the AI analysis is checked:

- Gemini receives the company's SEC XBRL figures (revenue, margins, cash flows, buybacks, EPS, latest quarter) and is told to use those exact values and not to calculate new ones. Quarterly figures are generally unaudited. It runs at temperature 0.
- Every insight must quote one sentence from the filing. The quote is matched against the filing text.
- Every dollar amount and percentage in an insight's headline and paragraph is checked for a numerical match in the filing text (including tables with a nearby stated scale) or XBRL data, including recent margins and growth rates derived from it.
- Insights whose quote is not found are hidden by default. Figures that could not be traced are underlined.

These checks confirm that the quote appears in the source and that the numerical values appear somewhere in the filing or XBRL data. They do not prove a value belongs to the claimed metric or period, or that the AI used it in the right context. Review the original filings before using the output in an investment decision.

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
