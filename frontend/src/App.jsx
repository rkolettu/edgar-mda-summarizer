import { ArrowUpRight, ExternalLink, Info, TriangleAlert } from 'lucide-react'
import { useState } from 'react'
import AnalysisSection from './components/AnalysisSection'
import CapitalDeploymentChart from './components/CapitalDeploymentChart'
import ChangesSection from './components/ChangesSection'
import KpiStrip from './components/KpiStrip'
import LatestQuarter from './components/LatestQuarter'
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
  item5: 'Item 5 operating review',
  operating_review: 'Annual report operating review',
  mdna_exhibit: 'Management discussion exhibit',
}

const SECTIONS = [
  { key: 'revenue_drivers', title: 'Revenue drivers' },
  { key: 'capital_allocation', title: 'Capital allocation' },
  { key: 'macro_risks', title: 'Macro risks' },
]

function CompanyHeader({ data }) {
  const { filing } = data

  return (
    <div className="mb-9 border-b border-line pb-7">
      <div>
        <div className="mb-3 text-[11px] font-semibold tracking-[0.14em] text-muted uppercase">Company research / {data.ticker}</div>
        <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
          <h1 className="break-words text-4xl leading-none font-semibold tracking-[-0.055em] text-ink sm:text-5xl">{data.company_name || data.ticker}</h1>
        </div>
        <p className="mt-3 text-base text-ink-2">{fiscalYearLabel(filing.report_date)} {filing.form} · Management discussion &amp; analysis</p>
      </div>

      <dl className="mt-7 flex flex-wrap items-center gap-x-7 gap-y-3 border-t border-line pt-4 text-xs">
        <div className="flex gap-1.5">
          <dt className="text-muted">{filing.form} filed</dt>
          <dd className="font-mono text-ink">{filing.filing_date}</dd>
        </div>
        {data.generated_at && (
          <div className="flex gap-1.5">
            <dt className="text-muted">Generated</dt>
            <dd className="font-mono text-ink-2">
              {new Date(data.generated_at).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })}
            </dd>
          </div>
        )}
        <div className="flex gap-1.5">
          <dt className="text-muted">Source</dt>
          <dd className="text-ink">{MDNA_SOURCE_LABELS[filing.mdna_source] ?? 'SEC filing'}</dd>
        </div>
        {filing.document_url && (
          <a
            href={filing.document_url}
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-1 font-medium text-accent hover:text-accent-hover"
          >
            View filing <ExternalLink size={12} />
          </a>
        )}
        {filing.mdna_url && filing.mdna_url !== filing.document_url && (
          <a
            href={filing.mdna_url}
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-1 font-medium text-accent hover:text-accent-hover"
          >
            View management discussion exhibit <ExternalLink size={12} />
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
        <li key={w} className="flex items-start gap-2 border-l-2 border-line bg-panel-2 px-4 py-3 text-xs text-ink-2">
          <Info size={14} className="mt-px shrink-0 text-muted" />
          {w}
        </li>
      ))}
    </ul>
  )
}

function EmptyState({ onPick }) {
  return (
    <div className="pt-10 sm:pt-16">
      <div className="grid gap-12 border-b border-line pb-16 lg:grid-cols-[minmax(0,1.35fr)_minmax(280px,0.65fr)] lg:items-end lg:gap-16 lg:pb-24">
        <div>
          <p className="mb-7 text-[11px] font-semibold tracking-[0.16em] text-accent uppercase">SEC EDGAR / Filing research</p>
          <h1 className="max-w-[12ch] text-[clamp(3.25rem,7vw,6.75rem)] leading-[0.98] font-semibold tracking-[-0.065em] text-ink">Read beyond the numbers.</h1>
        </div>
        <div className="lg:pb-2">
          <p className="max-w-md text-lg leading-relaxed text-ink-2">
            Start with a company. Follow the financials, see what management says changed, and trace each insight back to the filing.
          </p>
          <p className="mt-8 mb-3 text-[11px] font-semibold tracking-[0.12em] text-muted uppercase">Try a company</p>
          <div className="flex flex-wrap gap-2">
            {QUICK_TICKERS.map((t) => (
              <button
                key={t}
                onClick={() => onPick(t)}
                className="group inline-flex items-center gap-2 rounded-lg border border-line bg-panel px-3 py-2 font-mono text-xs text-ink transition-colors hover:border-ink"
              >
                {t}<ArrowUpRight size={12} className="text-muted group-hover:text-ink" aria-hidden />
              </button>
            ))}
          </div>
        </div>
      </div>
      <div className="grid gap-7 py-9 text-sm sm:grid-cols-3 sm:gap-10">
        <p className="text-ink-2"><span className="mr-3 font-mono text-xs text-muted">01</span> Five years of financial trends</p>
        <p className="text-ink-2"><span className="mr-3 font-mono text-xs text-muted">02</span> Changes in management's story</p>
        <p className="text-ink-2"><span className="mr-3 font-mono text-xs text-muted">03</span> Quotes from original filings</p>
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
  // Charts are in US dollars; hide them for filings reported in another (or an unverified) currency.
  const chartsHidden = Boolean(data?.filing.currency) && data.filing.currency !== 'USD'

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

      <main className="mx-auto w-full max-w-6xl flex-1 px-5 py-10 sm:px-8 sm:py-12">
        {loading && <LoadingState ticker={activeQuery} />}

        {error && !loading && (
          <div
            role="alert"
            className="mx-auto flex max-w-2xl items-start gap-3 rounded-xl border border-danger/30 bg-panel px-5 py-5 text-sm"
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
                <div className="mb-8 mt-10 flex items-end justify-between border-b border-line pb-3">
                  <h2 className="text-2xl font-semibold tracking-[-0.04em] text-ink">Financial trends</h2>
                  <span className="font-mono text-xs text-muted">SEC company facts</span>
                </div>
                <div className="mb-10 grid grid-cols-1 gap-5 lg:grid-cols-2">
                  <RevenueFcfChart years={data.financials.years} />
                  <MarginsChart years={data.financials.years} />
                </div>
              </>
            )}
            {data.latest_quarter && <LatestQuarter quarter={data.latest_quarter} />}
            <div className="mb-6 mt-12 border-b border-line pb-3">
              <p className="mb-1 text-[11px] font-semibold tracking-[0.14em] text-muted uppercase">Management commentary</p>
              <h2 className="text-2xl font-semibold tracking-[-0.04em] text-ink">Inside the filing</h2>
            </div>
            <div className={chartsHidden ? 'grid grid-cols-1 gap-5' : 'grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1.45fr)_minmax(0,1fr)]'}>
              <div className="space-y-5">
                {SECTIONS.map((s) => (
                  <AnalysisSection
                    key={s.key}
                    title={s.title}
                    insights={data.summary?.[s.key] ?? []}
                    sourceNote={s.key === 'macro_risks' && data.filing.risk_factors_found ? `Management discussion + ${data.filing.form === '10-K' ? 'Item 1A ' : ''}Risk Factors` : null}
                  />
                ))}
                {data.changes && <ChangesSection changes={data.changes} />}
              </div>
              {!chartsHidden && <aside className="space-y-5">
                <RevenueMixChart data={data.charts?.revenue_segments ?? []} check={data.checks?.segments} />
                <CapitalDeploymentChart
                  data={data.charts?.capital_deployment ?? []}
                  source={data.charts?.capital_deployment_source}
                />
              </aside>}
            </div>
          </>
        )}
      </main>

      <footer className="mx-auto flex w-full max-w-6xl flex-col justify-between gap-2 border-t border-line px-5 py-6 text-[11px] text-muted sm:flex-row sm:px-8">
        <span>Source: SEC EDGAR · Analysis: Gemini 2.5 Flash</span>
        <span>Research aid only. Review the original filing before making investment decisions.</span>
      </footer>
    </div>
  )
}
