# item7-extractor

Pulls the latest 10-K for a ticker from SEC EDGAR, extracts Item 7 (MD&A), and uses Gemini 2.5 Flash to summarize revenue drivers, capital allocation, and macro risks.

- `backend/`: FastAPI app serving `GET /api/summarize?ticker=AAPL` (accepts a ticker or company name) and `GET /api/search?q=apple` (autocomplete)
- `frontend/`: React + Vite + Tailwind CSS v4

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

Create two Vercel projects from this repo.

1. Backend: set Root Directory to `backend`. Vercel detects FastAPI from `main.py` and `requirements.txt`. Add the environment variable `GEMINI_API_KEY`.
2. Frontend: set Root Directory to `frontend` (framework preset: Vite). Add the environment variable `VITE_API_URL` = the backend's URL. It is read at build time, so redeploy after changing it.
