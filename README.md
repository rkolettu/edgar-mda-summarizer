# item7-extractor

Pulls the latest 10-K for a ticker from SEC EDGAR, extracts Item 7 (MD&A), and uses Gemini 2.5 Flash to summarize revenue drivers, capital allocation, and macro risks.

- `backend/`: FastAPI app serving `GET /api/summarize?ticker=AAPL` (accepts a ticker or company name) and `GET /api/search?q=apple` (autocomplete)
- `frontend/`: React + Vite + Tailwind CSS v4

## What it produces

- Summary tiles and 5-year revenue, free cash flow and margin trends from the SEC's structured XBRL data (`data.sec.gov` companyfacts)
- An AI-assisted research memo from the 10-K's Item 7 MD&A (or the Exhibit 13 annual report when Item 7 is incorporated by reference) and Item 1A Risk Factors, with each insight's source quote checked against the filing
- Revenue segments reconciled against reported revenue, and capital deployment from the cash flow statement
- What changed versus the prior year's 10-K
- A latest-quarter update from the most recent 10-Q filed after the 10-K
- Results cached per filing set in memory and at Vercel's CDN (`s-maxage=86400`)

When the app cannot isolate MD&A, it returns an error rather than summarizing an unrelated portion of the filing. A matching source quote confirms that the quoted words appear in the filing; it does not independently verify every statement in the AI analysis. Review the original filings before using the output in an investment decision.

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

## Deploying to Vercel

One Vercel project serves both apps (Vercel Services, configured in `vercel.json`): the frontend at `/` and the FastAPI backend at `/api`.

1. Import the repo at vercel.com/new and keep the **Services** preset it detects.
2. Add these environment variables:
   - `GEMINI_API_KEY`: your Gemini API key
   - `SEC_USER_AGENT`: an application name and real contact email, e.g. `Your Name Research (you@example.com)`
   - `VITE_API_URL`: `/` (the frontend calls `/api` on its own origin; the frontend build fails if this is missing)
3. Deploy.

To host the backend separately instead, deploy `backend/` as its own project with `GEMINI_API_KEY` and `SEC_USER_AGENT`, then set the frontend's `VITE_API_URL` to the backend's HTTPS origin, without `/api`. `VITE_API_URL` is read at build time, so redeploy after changing it. For a local production build, run `VITE_API_URL=http://localhost:8000 npm run build` from `frontend/`.
