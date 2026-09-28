import { Analytics } from '@vercel/analytics/react'
import { ArrowLeft, ExternalLink, Info, RefreshCw, Sparkles, TriangleAlert } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import AnalysisSection from './components/AnalysisSection'
import BusinessTab from './components/BusinessTab'
import CapitalDeploymentChart from './components/CapitalDeploymentChart'
import CapitalTab from './components/CapitalTab'
import ChangesSection from './components/ChangesSection'
import EarningsTab from './components/EarningsTab'
import FilingChangesTab from './components/FilingChangesTab'
import FilingChat from './components/FilingChat'
import FinancialsTab from './components/FinancialsTab'
import KpiStrip from './components/KpiStrip'
import Landing from './components/Landing'
import LatestQuarter from './components/LatestQuarter'
import LoadingState from './components/LoadingState'
import OverviewTab from './components/OverviewTab'
import RevenueMixChart from './components/RevenueMixChart'
import RisksTab from './components/RisksTab'
import SearchHeader from './components/SearchHeader'
import Tabs, { TabPanel } from './components/Tabs'
import { MarginsChart, RevenueFcfChart } from './components/TrendCharts'
import { getJson, postJson } from './lib/api'
import { fiscalYearLabel } from './lib/format'

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
  { key: 'business', label: 'Business & Strategy', short: 'Business' },
  { key: 'capital', label: 'Capital & Commitments', short: 'Capital' },
  { key: 'risks', label: 'Risks' },
  { key: 'earnings', label: 'Earnings Quality', short: 'Earnings' },
  { key: 'changes', label: 'Filing Changes', short: 'Changes' },
]

const RESEARCH_LOADING = "A company's first visit parses its recent annual and quarterly reports from SEC EDGAR, which can take up to a minute; later visits load from the database."
const INSIGHTS_LOADING = "Writing the AI analysis from the stored filings. A company's first visit takes about one to two minutes; later visits load instantly."

const SECTIONS = [
  { key: 'revenue_drivers', title: 'Revenue drivers' },
  { key: 'capital_allocation', title: 'Capital allocation' },
  { key: 'macro_risks', title: 'Macro risks' },
]

function CompanyHeader({ data, subtitle, onHome }) {
  const { filing } = data

  return (
    <div className="mb-9 border-b border-line pb-7">
      <div>
        <nav aria-label="Breadcrumb" className="mb-3 flex items-center gap-2 text-[11px] font-semibold tracking-[0.14em] text-muted uppercase">
          <button type="button" onClick={onHome} className="inline-flex items-center gap-1.5 text-accent uppercase hover:text-accent-hover">
            <ArrowLeft size={13} aria-hidden /> All companies
          </button>
          <span aria-hidden>/</span>
          <span>{data.ticker}</span>
        </nav>
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

function AnalysisStatus({ research, request, onGenerate }) {
  const meta = research.research_status
  if (!meta) return null
  if (meta.ai_status === 'complete') return (
    <div className="mb-4 flex justify-end">
      <button type="button" onClick={() => onGenerate(true)} disabled={request.status === 'loading'}
        className="inline-flex items-center gap-1.5 text-xs font-medium text-muted hover:text-accent disabled:opacity-60">
        <RefreshCw size={12} aria-hidden /> Refresh analysis
      </button>
    </div>
  )
  const failed = meta.ai_status === 'failed' || request.status === 'error'
  return (
    <div className="mb-6 flex flex-wrap items-center justify-between gap-3 border-l-2 border-accent bg-panel-2 px-4 py-3 text-sm">
      <div>
        <p className="font-medium text-ink">Filing data loaded. AI analysis was not generated.</p>
        {request.status === 'error' && <p className="mt-0.5 text-xs text-muted">{request.error}</p>}
      </div>
      {research.insights?.configured && (
        <button type="button" onClick={() => onGenerate(false)} disabled={request.status === 'loading'}
          className="inline-flex items-center gap-1.5 rounded bg-accent px-3 py-2 text-xs font-semibold text-white hover:bg-accent-hover disabled:opacity-60">
          {failed ? <RefreshCw size={13} aria-hidden /> : <Sparkles size={13} aria-hidden />}
          {failed ? 'Retry AI analysis' : 'Generate AI analysis'}
        </button>
      )}
    </div>
  )
}

// The header comes from the stored research, or from the legacy summary when the research store cannot serve the company.
function headerFor(summary, research) {
  if (research.status !== 'ready') return { data: summary.status === 'ready' ? summary.data : null }
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

// The legacy MD&A summary, shown only when the research store cannot serve the company.
function OverviewPanel({ summary }) {
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

export default function App() {
  const [query, setQuery] = useState('')
  const [activeQuery, setActiveQuery] = useState('')
  const [research, setResearch] = useState({ status: 'idle' })
  const [insightsRequest, setInsightsRequest] = useState({ status: 'idle' })
  // The legacy MD&A summary runs only when the research store cannot serve the company (not configured, or a filer
  // whose filings it cannot read), so a normal visit makes one set of model calls, once per filing.
  const [summary, setSummary] = useState({ status: 'idle' })
  const [tab, setTab] = useState('overview')
  const latestRequest = useRef(0)
  const searchInput = useRef(null)

  const researchReady = research.status === 'ready'
  // The page appears once everything it will show is ready, the AI analysis included (or known to be unavailable).
  const writingInsights = researchReady && insightsRequest.status === 'loading'
  const loading = research.status === 'loading' || writingInsights || (!researchReady && summary.status === 'loading')
  const showPage = (researchReady && !writingInsights) || summary.status === 'ready'
  const failed = !showPage && !loading && summary.status === 'error'
  const idle = research.status === 'idle' && summary.status === 'idle'
  const header = headerFor(summary, research)

  async function loadSummary(q, current) {
    setSummary({ status: 'loading' })
    try {
      const body = await getJson('/api/summarize', { ticker: q })
      if (!current()) return
      setSummary({ status: 'ready', data: body })
      setQuery(body.ticker)
    } catch (err) {
      if (current()) setSummary({ status: 'error', error: err.message || 'Unexpected error' })
    }
  }

  // Back to the landing page: from the logo, the breadcrumb or the browser's back button.
  function goHome({ push = true } = {}) {
    latestRequest.current += 1  // a company still loading no longer applies
    setQuery('')
    setActiveQuery('')
    setTab('overview')
    setResearch({ status: 'idle' })
    setSummary({ status: 'idle' })
    setInsightsRequest({ status: 'idle' })
    if (push && window.location.search) window.history.pushState({}, '', window.location.pathname)
    window.scrollTo(0, 0)
  }

  async function runAnalysis(input, { push = true } = {}) {
    const q = input.trim()
    if (!q || loading) return
    const request = ++latestRequest.current
    const current = () => request === latestRequest.current
    // The company is in the address (?c=TD), so a link opens it and the back button returns to the landing page.
    if (push && new URLSearchParams(window.location.search).get('c') !== q) {
      window.history.pushState({}, '', `?c=${encodeURIComponent(q)}`)
    }
    // Opened from the address or the back button: the search box keeps no focus, so its suggestions stay closed.
    if (!push) document.activeElement?.blur?.()

    setQuery(q)
    setActiveQuery(q)
    setTab('overview')
    setSummary({ status: 'idle' })
    setInsightsRequest({ status: 'idle' })
    setResearch({ status: 'loading' })

    let data
    try {
      data = await getJson(`/api/research/${encodeURIComponent(q)}`, {})
    } catch (err) {
      if (!current()) return
      const unconfigured = err.status === 503 && /not configured/i.test(err.message)
      setResearch({ status: unconfigured ? 'unavailable' : 'error', error: err.message || 'Unexpected error' })
      await loadSummary(q, current)
      return
    }
    if (!current()) return
    const ticker = data.company?.ticker ?? q
    setResearch({ status: 'ready', data })
    setQuery(ticker)
    if (ticker !== q) window.history.replaceState({}, '', `?c=${encodeURIComponent(ticker)}`)

  }

  async function generateInsights(force = false) {
    if (!research.data || insightsRequest.status === 'loading') return
    const request = latestRequest.current
    const current = () => request === latestRequest.current
    const ticker = research.data.company.ticker
    setInsightsRequest({ status: 'loading' })
    try {
      const suffix = force ? '?refresh=true' : ''
      const updated = await postJson(`/api/research/${encodeURIComponent(ticker)}/insights${suffix}`)
      if (!current()) return
      setResearch({ status: 'ready', data: updated })
      setInsightsRequest({ status: 'done' })
    } catch (err) {
      if (current()) setInsightsRequest({ status: 'error', error: err.message || 'Unexpected error' })
    }
  }

  // The latest handlers, for the listeners registered once below.
  const navigation = useRef({})
  useEffect(() => {
    navigation.current = { runAnalysis, goHome }
  })
  useEffect(() => {
    const open = () => {
      const c = new URLSearchParams(window.location.search).get('c')
      if (c) navigation.current.runAnalysis(c, { push: false })
      else navigation.current.goHome({ push: false })
    }
    if (new URLSearchParams(window.location.search).get('c')) open()
    window.addEventListener('popstate', open)
    return () => window.removeEventListener('popstate', open)
  }, [])

  // The landing page's "Search a company" buttons: back to the top, into the search box.
  function focusSearch() {
    window.scrollTo({ top: 0, behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' })
    searchInput.current?.focus({ preventScroll: true })
  }

  const tabProps = { research: research.data, request: insightsRequest }
  return (
    <div className="flex min-h-screen flex-col bg-page">
      <SearchHeader query={query} onQueryChange={setQuery} onSubmit={runAnalysis} loading={loading} onHome={goHome} inputRef={searchInput} />

      {idle && <main className="flex-1"><Landing onPick={runAnalysis} onSearch={focusSearch} /></main>}

      {!idle && <main className="mx-auto w-full max-w-6xl flex-1 px-5 py-10 sm:px-8 sm:py-12">
        {loading && (
          <LoadingState
            ticker={activeQuery}
            message={research.status === 'loading' ? RESEARCH_LOADING : writingInsights ? INSIGHTS_LOADING : undefined}
          />
        )}

        {failed && <FailureAlert query={activeQuery} message={summary.error} />}

        {showPage && (
          <>
            <CompanyHeader data={header.data} subtitle={header.subtitle} onHome={goHome} />
            {researchReady ? (
              <>
                <Tabs tabs={TABS} active={tab} onChange={setTab} />
                <AnalysisStatus research={research.data} request={insightsRequest} onGenerate={generateInsights} />
                <TabPanel tabKey="overview" active={tab}><OverviewTab {...tabProps} onNavigate={setTab} /></TabPanel>
                <TabPanel tabKey="financials" active={tab}><FinancialsTab research={research.data} /></TabPanel>
                <TabPanel tabKey="business" active={tab}><BusinessTab {...tabProps} /></TabPanel>
                <TabPanel tabKey="capital" active={tab}><CapitalTab research={research.data} /></TabPanel>
                <TabPanel tabKey="risks" active={tab}><RisksTab {...tabProps} /></TabPanel>
                <TabPanel tabKey="earnings" active={tab}><EarningsTab {...tabProps} /></TabPanel>
                <TabPanel tabKey="changes" active={tab}><FilingChangesTab research={research.data} /></TabPanel>
                {research.data.chat?.configured && <FilingChat key={research.data.company.ticker} research={research.data} />}
              </>
            ) : (
              <OverviewPanel summary={summary} />
            )}
          </>
        )}
      </main>}

      <footer className="mx-auto flex w-full max-w-6xl flex-col justify-between gap-2 border-t border-line px-5 py-6 text-[11px] text-muted sm:flex-row sm:px-8">
        <span>Source: SEC EDGAR · AI analysis: Google Gemini (free tier), checked against the filings · A personal project</span>
        <span>Research aid only. Review the original filing before making investment decisions.</span>
      </footer>
      <Analytics />
    </div>
  )
}
