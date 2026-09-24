# item7-extractor

Pulls the latest 10-K for a ticker from SEC EDGAR, extracts Item 7 (MD&A), and uses Gemini 2.5 Flash to summarize revenue drivers, capital allocation, and macro risks.

- `backend/`: FastAPI app serving `GET /api/summarize?ticker=AAPL` (accepts a ticker or company name) and `GET /api/search?q=apple` (autocomplete)
- `frontend/`: React + Vite + Tailwind CSS v4

## What it produces

- Summary tiles and 5-year revenue, free cash flow and margin trends from the SEC's structured XBRL data (`data.sec.gov` companyfacts)
- A buy-side memo from the 10-K's Item 7 MD&A (or the Exhibit 13 annual report when Item 7 is incorporated by reference) and Item 1A Risk Factors, with each insight's source quote checked against the filing
- Revenue segments reconciled against reported revenue, and capital deployment from the cash flow statement
- What changed versus the prior year's 10-K
- A latest-quarter update from the most recent 10-Q filed after the 10-K
- Results cached per filing set in memory and at Vercel's CDN (`s-maxage=86400`)

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
uvicorn main:app --reload --port 8000
```

Frontend (terminal 2):

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173.

## Deploying to Vercel

One Vercel project serves both apps (Vercel Services, configured in `vercel.json`): the frontend at `/` and the FastAPI backend at `/api`.

1. Import the repo at vercel.com/new and keep the **Services** preset it detects.
2. Add the environment variable `GEMINI_API_KEY`.
3. Deploy.

The frontend calls `/api` on its own origin in production, so `VITE_API_URL` is not needed. Set it only to point the frontend at a separately hosted backend.
