import { useEffect, useState } from 'react'

const API_BASE = (import.meta.env.VITE_API_URL || 'http://localhost:8000').replace(/\/$/, '')

const SECTIONS = [
  { key: 'revenue_drivers', code: 'REV', title: 'Revenue Drivers', accent: 'text-term-green', bar: 'bg-term-green' },
  { key: 'capital_allocation', code: 'CAP', title: 'Capital Allocation', accent: 'text-term-cyan', bar: 'bg-term-cyan' },
  { key: 'macro_risks', code: 'RSK', title: 'Macro Risks', accent: 'text-term-red', bar: 'bg-term-red' },
]

const LOADING_STEPS = [
  'RESOLVING TICKER -> CIK',
  'PULLING EDGAR SUBMISSIONS',
  'DOWNLOADING LATEST 10-K',
  'PARSING ITEM 7 (MD&A)',
  'RUNNING GEMINI ANALYSIS',
]

function Clock() {
  const [now, setNow] = useState(new Date())
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(id)
  }, [])
  return <span>{now.toLocaleTimeString('en-US', { hour12: false })}</span>
}

function LoadingPanel({ ticker }) {
  const [elapsed, setElapsed] = useState(0)
  useEffect(() => {
    const id = setInterval(() => setElapsed((e) => e + 0.1), 100)
    return () => clearInterval(id)
  }, [])
  const step = Math.min(Math.floor(elapsed / 2), LOADING_STEPS.length - 1)

  return (
    <div className="mx-auto mt-10 max-w-2xl border border-term-border bg-term-panel p-6">
      <div className="mb-4 flex items-center justify-between text-xs">
        <span className="text-term-amber">PROCESSING {ticker}</span>
        <span className="text-term-muted">{elapsed.toFixed(1)}s</span>
      </div>
      <ul className="space-y-2 text-sm">
        {LOADING_STEPS.map((label, i) => (
          <li key={label} className="flex items-center gap-3">
            <span
              className={
                i < step ? 'text-term-green' : i === step ? 'text-term-amber' : 'text-term-border'
              }
            >
              {i < step ? '[OK]' : i === step ? '[..]' : '[  ]'}
            </span>
            <span className={i <= step ? 'text-gray-200' : 'text-term-muted'}>
              {label}
              {i === step && <span className="cursor-blink">_</span>}
            </span>
          </li>
        ))}
      </ul>
      <div className="mt-5 h-1 w-full bg-term-border">
        <div
          className="h-1 bg-term-amber transition-all duration-100"
          style={{ width: `${Math.min((elapsed / 12) * 100, 95)}%` }}
        />
      </div>
      <p className="mt-3 text-xs text-term-muted">SEC fetch + Gemini analysis typically takes ~10s.</p>
    </div>
  )
}

function SectionPanel({ section, items }) {
  return (
    <section className="flex flex-col border border-term-border bg-term-panel">
      <header className="flex items-center justify-between border-b border-term-border bg-term-amber px-3 py-1.5 text-black">
        <span className="text-xs font-bold tracking-widest">{section.title.toUpperCase()}</span>
        <span className="text-xs font-bold">{section.code}</span>
      </header>
      <div className={`h-0.5 w-full ${section.bar}`} />
      {items.length === 0 ? (
        <p className="p-4 text-sm text-term-muted">No data returned.</p>
      ) : (
        <ul className="space-y-3 p-4">
          {items.map((item, i) => (
            <li key={i} className="flex gap-3 text-sm leading-relaxed">
              <span className={`shrink-0 font-bold ${section.accent}`}>
                {String(i + 1).padStart(2, '0')}
              </span>
              <span className="text-gray-200">{item}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

export default function App() {
  const [ticker, setTicker] = useState('')
  const [activeTicker, setActiveTicker] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [data, setData] = useState(null)

  async function handleSubmit(e) {
    e.preventDefault()
    const t = ticker.trim().toUpperCase()
    if (!t || loading) return

    setActiveTicker(t)
    setLoading(true)
    setError('')
    setData(null)

    try {
      const res = await fetch(`${API_BASE}/api/summarize?ticker=${encodeURIComponent(t)}`)
      const body = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(body.detail || `Request failed (${res.status})`)
      setData(body)
    } catch (err) {
      setError(err.message || 'Unexpected error')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen flex-col bg-term-bg">
      <div className="flex items-center justify-between border-b border-term-border bg-term-panel px-4 py-1.5 text-xs">
        <div className="flex items-center gap-4">
          <span className="font-bold text-term-amber">ITEM7&lt;GO&gt;</span>
          <span className="hidden text-term-muted sm:inline">SEC 10-K MD&amp;A EXTRACTOR</span>
        </div>
        <div className="flex items-center gap-4 text-term-muted">
          <span className="flex items-center gap-1.5">
            <span className="h-1.5 w-1.5 rounded-full bg-term-green" />
            LIVE
          </span>
          <Clock />
        </div>
      </div>

      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-10">
        <div className="text-center">
          <h1 className="text-2xl font-bold tracking-widest text-term-amber sm:text-3xl">ITEM 7 EXTRACTOR</h1>
          <p className="mt-2 text-xs tracking-wider text-term-muted">
            MANAGEMENT&apos;S DISCUSSION &amp; ANALYSIS // BUY-SIDE SUMMARY
          </p>
        </div>

        <form onSubmit={handleSubmit} className="mx-auto mt-8 flex max-w-xl border border-term-amber">
          <span className="flex items-center bg-term-amber px-3 text-sm font-bold text-black">&gt;</span>
          <input
            value={ticker}
            onChange={(e) => setTicker(e.target.value.toUpperCase())}
            placeholder="ENTER TICKER (e.g. AAPL)"
            maxLength={10}
            autoFocus
            spellCheck={false}
            className="min-w-0 flex-1 bg-black px-4 py-3 text-lg tracking-widest text-term-amber uppercase placeholder:text-term-muted placeholder:text-sm focus:outline-none"
          />
          <button
            type="submit"
            disabled={loading || !ticker.trim()}
            className="bg-term-amber px-5 text-sm font-bold tracking-widest text-black transition-colors hover:bg-amber-300 disabled:cursor-not-allowed disabled:bg-term-border disabled:text-term-muted"
          >
            {loading ? 'WAIT' : 'GO'}
          </button>
        </form>

        {loading && <LoadingPanel ticker={activeTicker} />}

        {error && !loading && (
          <div className="mx-auto mt-10 max-w-2xl border border-term-red bg-term-panel p-4 text-sm">
            <span className="font-bold text-term-red">ERR </span>
            <span className="text-gray-200">{error}</span>
          </div>
        )}

        {data && !loading && (
          <div className="mt-10">
            <div className="mb-4 flex flex-wrap items-baseline gap-x-6 gap-y-1 border-b border-term-border pb-3 text-xs">
              <span className="text-lg font-bold text-term-amber">{data.ticker} US Equity</span>
              {data.company_name && <span className="text-gray-200">{data.company_name}</span>}
              {data.filing_date && (
                <span className="text-term-muted">
                  10-K FILED <span className="text-gray-200">{data.filing_date}</span>
                </span>
              )}
              {data.extraction_method && (
                <span className="text-term-muted">
                  SOURCE{' '}
                  <span className={data.extraction_method === 'item7' ? 'text-term-green' : 'text-term-amber'}>
                    {data.extraction_method === 'item7' ? 'ITEM 7 MD&A' : 'FULL DOC (TRUNCATED)'}
                  </span>
                </span>
              )}
              {data.document_url && (
                <a
                  href={data.document_url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-term-cyan underline-offset-2 hover:underline"
                >
                  VIEW FILING &rarr;
                </a>
              )}
            </div>

            <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
              {SECTIONS.map((s) => (
                <SectionPanel key={s.key} section={s} items={Array.isArray(data[s.key]) ? data[s.key] : []} />
              ))}
            </div>
          </div>
        )}
      </main>

      <footer className="border-t border-term-border px-4 py-2 text-center text-[10px] tracking-wider text-term-muted">
        DATA: SEC EDGAR // ANALYSIS: GEMINI 2.5 FLASH // NOT INVESTMENT ADVICE
      </footer>
    </div>
  )
}
