# Item 7 Extractor

Look up a U.S. public company by name or ticker, retrieve its latest 10-K from SEC EDGAR, and summarize Item 7 (Management's Discussion and Analysis) with Gemini 2.5 Flash. The interface presents revenue drivers, capital allocation, macro risks, and charts when comparable figures are disclosed.

[Live app](https://edgar-10k-and-mda-summarizer.vercel.app/)

## How it works

1. `GET /api/search?q=apple` matches a name or ticker against the SEC company list.
2. `GET /api/summarize?ticker=AAPL` looks up the latest 10-K and extracts the text between Item 7 and Item 8.
3. Gemini returns a structured analysis. Chart values are requested in USD billions; charts are left empty when the source lacks comparable figures.

If Item 7 cannot be isolated, the API returns an error instead of summarizing an unrelated portion of the filing. Read the linked 10-K and verify any AI-generated analysis before relying on it. This is a research aid, not investment advice.

The backend is FastAPI. The frontend uses React, Vite, Tailwind CSS, and Recharts.

## Run locally

Backend (terminal 1):

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export SEC_USER_AGENT="Your Name Research (you@example.com)"
export GEMINI_API_KEY="your-key-here"
uvicorn main:app --reload --port 8000
```

Frontend (terminal 2):

```bash
cd frontend
npm ci
npm run dev
```

Open http://localhost:5173. `backend/.env.example` lists the backend variables; the app reads them from the process environment. Do not commit real keys. Use a real contact email in `SEC_USER_AGENT` so the SEC can identify the application.

## Checks

```bash
cd backend && ../.venv/bin/python -m unittest discover -s tests -v
cd ../frontend && npm run lint && npm run build
```

## Deploying to Vercel

Create two Vercel projects from this repo.

1. Backend: set Root Directory to `backend`. Vercel detects FastAPI from `main.py` and `requirements.txt`. Add `GEMINI_API_KEY` and `SEC_USER_AGENT` as environment variables. Use a real application name and contact email for the latter.
2. Frontend: set Root Directory to `frontend` (framework preset: Vite). Add the environment variable `VITE_API_URL` = the backend's URL. It is read at build time, so redeploy after changing it.
