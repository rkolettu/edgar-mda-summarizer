import { ExternalLink, Info, Landmark, ShieldAlert, TrendingUp, TriangleAlert } from 'lucide-react'
import { useState } from 'react'
import AnalysisSection from './components/AnalysisSection'
import CapitalDeploymentChart from './components/CapitalDeploymentChart'
import ChangesSection from './components/ChangesSection'
import KpiStrip from './components/KpiStrip'
import LoadingState from './components/LoadingState'
import RevenueMixChart from './components/RevenueMixChart'
import SearchHeader from './components/SearchHeader'
import { MarginsChart, RevenueFcfChart } from './components/TrendCharts'
import { getJson } from './lib/api'
import { fiscalYearLabel } from './lib/format'

const QUICK_TICKERS = ['AAPL', 'MSFT', 'NVDA', 'AMZN', 'JPM']

const MDNA_SOURCE_LABELS = {
  item7: 'Item 7 MD&A',
  exhibit13: 'Annual report MD&A (Exhibit 13)',
  fallback: 'Full filing (Item 7 not isolated)',
}

const SECTIONS = [
  { key: 'revenue_drivers', title: 'Revenue Drivers', icon: TrendingUp },
  { key: 'capital_allocation', title: 'Capital Allocation', icon: Landmark },
  { key: 'macro_risks', title: 'Macro Risks', icon: ShieldAlert },
]

function CompanyHeader({ data }) {
  const { filing } = data
  const isFallback = filing.mdna_source === 'fallback'

  return (
    <div className="mb-6 flex flex-col gap-3 border-b border-line pb-5 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h1 className="text-2xl font-semibold tracking-tight text-ink">{data.company_name || data.ticker}</h1>
          <span className="rounded border border-line bg-panel px-1.5 py-0.5 font-mono text-xs text-ink-2">
            {data.ticker}
          </span>
        </div>
        <p className="mt-1 text-sm text-ink-2">{fiscalYearLabel(filing.report_date)} MD&amp;A Analysis</p>
      </div>

      <dl className="flex flex-wrap items-center gap-x-5 gap-y-2 text-xs">
        <div className="flex gap-1.5">
          <dt className="text-muted">10-K filed</dt>
          <dd className="font-mono text-ink-2">{filing.filing_date}</dd>
        </div>
        <div className="flex gap-1.5">
          <dt className="text-muted">Source</dt>
          <dd className={isFallback ? 'text-[#c98500]' : 'text-ink-2'}>{MDNA_SOURCE_LABELS[filing.mdna_source]}</dd>
        </div>
        {filing.document_url && (
          <a
            href={filing.document_url}
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-1 text-accent hover:text-accent-hover"
          >
            View filing <ExternalLink size={12} />
          </a>
        )}
        {filing.mdna_url && filing.mdna_url !== filing.document_url && (
          <a
            href={filing.mdna_url}
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-1 text-accent hover:text-accent-hover"
          >
            View MD&amp;A exhibit <ExternalLink size={12} />
          </a>
        )}
      </dl>
    </div>
  )
}

function Warnings({ items }) {
  if (!items?.length) return null
  return (
    <ul className="mb-6 space-y-1.5">
      {items.map((w) => (
        <li key={w} className="flex items-start gap-2 rounded-md border border-line bg-panel px-3 py-2 text-xs text-ink-2">
          <Info size={14} className="mt-px shrink-0 text-muted" />
          {w}
        </li>
      ))}
    </ul>
  )
}

function EmptyState({ onPick }) {
  return (
    <div className="mx-auto max-w-xl py-20 text-center">
      <h1 className="text-2xl font-semibold tracking-tight text-ink">Institutional-grade 10-K MD&amp;A analysis</h1>
      <p className="mt-3 text-sm leading-relaxed text-ink-2">
        Search by company name or ticker to pull the latest 10-K from SEC EDGAR, isolate Item 7, and generate a buy-side memo on
        revenue drivers, capital allocation, and macro risk.
      </p>
      <div className="mt-6 flex flex-wrap justify-center gap-2">
        {QUICK_TICKERS.map((t) => (
          <button
            key={t}
            onClick={() => onPick(t)}
            className="rounded-md border border-line bg-panel px-3 py-1.5 font-mono text-xs text-ink-2 transition-colors hover:border-accent hover:text-ink"
          >
            {t}
          </button>
        ))}
      </div>
    </div>
  )
}

export default function App() {
  const [query, setQuery] = useState('')
  const [activeQuery, setActiveQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [data, setData] = useState(null)

  async function runAnalysis(input) {
    const q = input.trim()
    if (!q || loading) return

    setQuery(q)
    setActiveQuery(q)
    setLoading(true)
    setError('')
    setData(null)

    try {
      const body = await getJson('/api/summarize', { ticker: q })
      setData(body)
      setQuery(body.ticker)
    } catch (err) {
      setError(err.message || 'Unexpected error')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen flex-col bg-page">
      <SearchHeader query={query} onQueryChange={setQuery} onSubmit={runAnalysis} loading={loading} />

      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-8 sm:px-6">
        {loading && <LoadingState ticker={activeQuery} />}

        {error && !loading && (
          <div
            role="alert"
            className="mx-auto flex max-w-2xl items-start gap-3 rounded-lg border border-danger/40 bg-danger/5 px-4 py-3 text-sm"
          >
            <TriangleAlert size={17} className="mt-0.5 shrink-0 text-danger" />
            <div>
              <div className="font-medium text-ink">Analysis failed for “{activeQuery}”</div>
              <div className="mt-0.5 text-ink-2">{error}</div>
            </div>
          </div>
        )}

        {!loading && !error && !data && <EmptyState onPick={runAnalysis} />}

        {data && !loading && (
          <>
            <CompanyHeader data={data} />
            <Warnings items={data.warnings} />
            {data.financials && (
              <>
                <KpiStrip kpis={data.financials.kpis} />
                <div className="mb-6 grid grid-cols-1 gap-6 lg:grid-cols-2">
                  <RevenueFcfChart years={data.financials.years} />
                  <MarginsChart years={data.financials.years} />
                </div>
              </>
            )}
            <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1.45fr)_minmax(0,1fr)]">
              <div className="space-y-6">
                {SECTIONS.map((s) => (
                  <AnalysisSection
                    key={s.key}
                    title={s.title}
                    icon={s.icon}
                    insights={data.summary?.[s.key] ?? []}
                    sourceNote={s.key === 'macro_risks' && data.filing.risk_factors_found ? 'MD&A + Item 1A Risk Factors' : null}
                  />
                ))}
                {data.changes && <ChangesSection changes={data.changes} />}
              </div>
              <aside className="space-y-6 lg:sticky lg:top-24 lg:self-start">
                <RevenueMixChart data={data.charts?.revenue_segments ?? []} check={data.checks?.segments} />
                <CapitalDeploymentChart
                  data={data.charts?.capital_deployment ?? []}
                  source={data.charts?.capital_deployment_source}
                />
              </aside>
            </div>
          </>
        )}
      </main>

      <footer className="border-t border-line px-4 py-3 text-center text-[11px] text-muted">
        Data: SEC EDGAR · Analysis: Gemini 2.5 Flash · Not investment advice
      </footer>
    </div>
  )
}
