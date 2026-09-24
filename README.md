# item7-extractor

Pulls the latest 10-K for a ticker from SEC EDGAR, extracts Item 7 (MD&A), and uses Gemini 2.5 Flash to summarize revenue drivers, capital allocation, and macro risks.

- `backend/`: FastAPI app serving `GET /api/summarize?ticker=AAPL`
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

## Deploying the frontend to Vercel

- Root Directory: `frontend` (framework preset: Vite)
- Environment variable: `VITE_API_URL` = public URL of the deployed backend (defaults to `http://localhost:8000`)

The backend must be hosted somewhere publicly reachable (e.g. Render, Railway, Fly.io) with `GEMINI_API_KEY` set.
