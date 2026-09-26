import { Analytics } from '@vercel/analytics/react'
import { ArrowUpRight, ExternalLink, Info, TriangleAlert } from 'lucide-react'
import { useRef, useState } from 'react'
import AnalysisSection from './components/AnalysisSection'
import CapitalDeploymentChart from './components/CapitalDeploymentChart'
import CapitalTab from './components/CapitalTab'
import ChangesSection from './components/ChangesSection'
import FilingChangesTab from './components/FilingChangesTab'
import FinancialsTab from './components/FinancialsTab'
import KpiStrip from './components/KpiStrip'
import LatestQuarter from './components/LatestQuarter'
import LoadingState from './components/LoadingState'
import RevenueMixChart from './components/RevenueMixChart'
import SearchHeader from './components/SearchHeader'
import Tabs, { TabPanel } from './components/Tabs'
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

const TABS = [
  { key: 'overview', label: 'Overview' },
  { key: 'financials', label: 'Financials' },
  { key: 'capital', label: 'Capital & Commitments', short: 'Capital' },
  { key: 'changes', label: 'Filing Changes', short: 'Changes' },
]

const SECTIONS = [
  { key: 'revenue_drivers', title: 'Revenue drivers' },
  { key: 'capital_allocation', title: 'Capital allocation' },
  { key: 'macro_risks', title: 'Macro risks' },
]

function CompanyHeader({ data, subtitle }) {
  const { filing } = data

  return (
    <div className="mb-9 border-b border-line pb-7">
      <div>
        <div className="mb-3 text-[11px] font-semibold tracking-[0.14em] text-muted uppercase">Company research / {data.ticker}</div>
        <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
          <h1 className="break-words text-4xl leading-none font-semibold tracking-[-0.055em] text-ink sm:text-5xl">{data.company_name || data.ticker}</h1>
        </div>
        <p className="mt-3 text-base text-ink-2">
          {subtitle ?? <>{fiscalYearLabel(filing.report_date)} {filing.form} · Management discussion &amp; analysis</>}
        </p>
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

function FailureAlert({ query, message }) {
  return (
    <div role="alert" className="mx-auto flex max-w-2xl items-start gap-3 rounded-xl border border-danger/30 bg-panel px-5 py-5 text-sm">
      <TriangleAlert size={17} className="mt-0.5 shrink-0 text-danger" />
      <div>
        <div className="font-medium text-ink">Analysis failed for “{query}”</div>
        <div className="mt-0.5 text-ink-2">{message}</div>
      </div>
    </div>
  )
}

function Notice({ children }) {
  return <p className="flex items-start gap-2 rounded-xl border border-line bg-panel px-5 py-4 text-sm text-ink-2"><Info size={15} className="mt-0.5 shrink-0 text-muted" />{children}</p>
}

// The header comes from the AI analysis when it has arrived, otherwise from the stored research.
function headerFor(summary, research) {
  if (summary.status === 'ready') return { data: summary.data }
  if (research.status !== 'ready') return { data: null }
  const r = research.data
  const latest = r.filings.find((f) => f.accession_number === r.latest_filing) ?? r.filings[0]
  return {
    data: {
      ticker: r.company.ticker,
      company_name: r.company.name,
      generated_at: r.generated_at,
      filing: { form: latest?.form, filing_date: latest?.filing_date, report_date: latest?.period_end, document_url: latest?.source_url },
    },
    subtitle: latest ? `Latest filing: ${latest.fiscal_label} ${latest.form}` : 'SEC filings',
  }
}

function OverviewPanel({ summary, ticker }) {
  if (summary.status === 'loading') return <LoadingState ticker={ticker} />
  if (summary.status === 'error') {
    return <Notice>The AI summary is unavailable right now ({summary.error}). The Financials and Capital &amp; Commitments tabs are built from the filings' tagged data and do not depend on it.</Notice>
  }
  const data = summary.data
  // Charts are in US dollars; hide them for filings reported in another (or an unverified) currency.
  const chartsHidden = Boolean(data.filing.currency) && data.filing.currency !== 'USD'
  return (
    <>
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
  )
}

function ResearchPanel({ research, children }) {
  if (research.status === 'ready') return children(research.data)
  if (research.status === 'loading') {
    return <Notice>Reading the company's filings. A first visit parses its recent annual and quarterly reports, which can take up to a minute; later visits load from the database.</Notice>
  }
  return <Notice>Structured filing data is unavailable: {research.error}</Notice>
}

export default function App() {
  const [query, setQuery] = useState('')
  const [activeQuery, setActiveQuery] = useState('')
  const [summary, setSummary] = useState({ status: 'idle' })
  const [research, setResearch] = useState({ status: 'idle' })
  const [tab, setTab] = useState('overview')
  const latestRequest = useRef(0)

  // The stored research usually answers in about a second; the AI summary can take a minute on a first visit.
  // The page shows as soon as either arrives, and each tab waits only for its own data.
  const loading = summary.status === 'loading' && research.status !== 'ready'
  const researchReady = research.status === 'ready'
  const showPage = summary.status === 'ready' || researchReady
  const failed = summary.status === 'error' && !researchReady && research.status !== 'loading'
  const header = headerFor(summary, research)

  async function runAnalysis(input) {
    const q = input.trim()
    if (!q || loading) return
    const request = ++latestRequest.current
    const current = () => request === latestRequest.current

    setQuery(q)
    setActiveQuery(q)
    setTab('overview')
    setSummary({ status: 'loading' })
    setResearch({ status: 'loading' })

    getJson(`/api/research/${encodeURIComponent(q)}`, {})
      .then((data) => current() && setResearch({ status: 'ready', data }))
      .catch((err) => {
        if (!current()) return
        const unconfigured = err.status === 503 && /not configured/i.test(err.message)
        setResearch({ status: unconfigured ? 'unavailable' : 'error', error: err.message || 'Unexpected error' })
      })

    try {
      const body = await getJson('/api/summarize', { ticker: q })
      if (!current()) return
      setSummary({ status: 'ready', data: body })
      setQuery(body.ticker)
    } catch (err) {
      if (current()) setSummary({ status: 'error', error: err.message || 'Unexpected error' })
    }
  }

  return (
    <div className="flex min-h-screen flex-col bg-page">
      <SearchHeader query={query} onQueryChange={setQuery} onSubmit={runAnalysis} loading={loading} />

      <main className="mx-auto w-full max-w-6xl flex-1 px-5 py-10 sm:px-8 sm:py-12">
        {loading && <LoadingState ticker={activeQuery} />}

        {failed && <FailureAlert query={activeQuery} message={summary.error} />}

        {summary.status === 'idle' && <EmptyState onPick={runAnalysis} />}

        {showPage && (
          <>
            <CompanyHeader data={header.data} subtitle={header.subtitle} />
            {research.status !== 'unavailable' && <Tabs tabs={TABS} active={tab} onChange={setTab} />}
            <TabPanel tabKey="overview" active={research.status === 'unavailable' ? 'overview' : tab}>
              <OverviewPanel summary={summary} ticker={activeQuery} />
            </TabPanel>
            <TabPanel tabKey="financials" active={tab}>
              <ResearchPanel research={research}>{(data) => <FinancialsTab research={data} />}</ResearchPanel>
            </TabPanel>
            <TabPanel tabKey="capital" active={tab}>
              <ResearchPanel research={research}>{(data) => <CapitalTab research={data} />}</ResearchPanel>
            </TabPanel>
            <TabPanel tabKey="changes" active={tab}>
              <ResearchPanel research={research}>{(data) => <FilingChangesTab research={data} />}</ResearchPanel>
            </TabPanel>
          </>
        )}
      </main>

      <footer className="mx-auto flex w-full max-w-6xl flex-col justify-between gap-2 border-t border-line px-5 py-6 text-[11px] text-muted sm:flex-row sm:px-8">
        <span>Source: SEC EDGAR · Analysis: Gemini 2.5 Flash</span>
        <span>Research aid only. Review the original filing before making investment decisions.</span>
      </footer>
      <Analytics />
    </div>
  )
}
