import { Analytics } from '@vercel/analytics/react'
import { ArrowLeft, ArrowUpRight, ExternalLink, Info, TriangleAlert } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import AnalysisSection from './components/AnalysisSection'
import BusinessTab from './components/BusinessTab'
import CapitalDeploymentChart from './components/CapitalDeploymentChart'
import CapitalTab from './components/CapitalTab'
import ChangesSection from './components/ChangesSection'
import CompanySearch from './components/CompanySearch'
import EarningsTab from './components/EarningsTab'
import FilingChangesTab from './components/FilingChangesTab'
import FilingChat from './components/FilingChat'
import FinancialsTab from './components/FinancialsTab'
import KpiStrip from './components/KpiStrip'
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

function EmptyState({ onPick, query, onQueryChange }) {
  return (
    <div className="pt-5 sm:pt-10">
      <div className="border-b border-line pb-10 sm:pb-12">
        <p className="mb-5 flex items-center gap-3 text-[11px] font-semibold tracking-[0.14em] text-gold uppercase before:h-[2px] before:w-6 before:bg-gold before:content-['']">Investment research</p>
        <h1 className="display-heading max-w-4xl text-[clamp(3.1rem,7vw,5.5rem)] leading-[1.06] font-medium tracking-[-0.035em] text-ink">Company filings.<br />Clearly summarized<span className="text-gold">.</span></h1>
        <p className="mt-5 max-w-2xl text-base leading-relaxed text-ink-2 sm:text-lg">
          Review management’s discussion of financial results, cash flow, and business risks. Start with a company name or ticker.
        </p>
      </div>
      <div className="flex flex-wrap items-baseline justify-between gap-2 py-6">
        <h2 className="display-heading text-3xl font-medium tracking-[-0.025em] text-ink">Start your research</h2>
        <span className="text-xs text-muted">Management discussion &amp; analysis</span>
      </div>
      <div className="grid gap-5 pb-12 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
        <section className="rounded-2xl border border-line bg-panel p-6 sm:p-8">
          <p className="mb-6 text-[11px] font-semibold tracking-[0.12em] text-muted uppercase">Company search</p>
          <h3 className="display-heading mb-2 text-3xl font-medium tracking-[-0.025em] text-ink">Find a company</h3>
          <p className="mb-6 text-sm text-ink-2">Search for the company you want to research.</p>
          <CompanySearch query={query} onQueryChange={onQueryChange} onSubmit={onPick} prominent />
          <p className="mt-6 mb-3 text-xs text-muted">Try a company</p>
          <div className="flex flex-wrap gap-2">
            {QUICK_TICKERS.map((t) => (
              <button key={t} onClick={() => onPick(t)}
                className="group inline-flex min-h-10 items-center gap-2 rounded-lg border border-line bg-panel px-3 py-2 font-mono text-xs text-ink transition-colors hover:border-gold">
                {t}<ArrowUpRight size={12} className="text-gold" aria-hidden />
              </button>
            ))}
          </div>
        </section>
        <section className="rounded-2xl border border-line bg-panel p-6 sm:p-8">
          <p className="mb-6 text-[11px] font-semibold tracking-[0.12em] text-muted uppercase">Inside the MD&amp;A</p>
          <h3 className="display-heading mb-2 text-3xl font-medium tracking-[-0.025em] text-ink">Management’s perspective</h3>
          <p className="mb-5 text-sm leading-relaxed text-ink-2">How management explains the company’s performance and financial position.</p>
          <ol className="divide-y divide-line text-sm text-ink">
            <li className="flex gap-4 py-3"><span className="font-mono text-xs text-gold">01</span> Operating results</li>
            <li className="flex gap-4 py-3"><span className="font-mono text-xs text-gold">02</span> Liquidity &amp; capital resources</li>
            <li className="flex gap-4 py-3"><span className="font-mono text-xs text-gold">03</span> Risks &amp; uncertainties</li>
          </ol>
        </section>
      </div>
      <AboutProject />
    </div>
  )
}

// What to expect: how the figures are read, which AI writes the analysis, and what kind of project this is.
function AboutProject() {
  return (
    <section aria-labelledby="about-heading" className="mb-6 rounded-2xl border border-line bg-panel px-6 py-6 sm:px-8 sm:py-7">
      <h2 id="about-heading" className="mb-4 flex items-center gap-2 text-base font-semibold tracking-[-0.025em] text-ink">
        <Info size={16} className="text-accent" aria-hidden /> A passion project, with some rough edges
      </h2>
      <div className="grid gap-5 text-sm leading-relaxed text-ink-2 md:grid-cols-3 md:gap-8">
        <p>
          <span className="font-semibold text-ink">Parsed, not hand-checked.</span> Figures are read by code from the
          machine-readable tags in each filing, and every company tags a little differently. Some tables can look off: a
          blank cell, an oddly worded label, a period that is missing. Where the tool can tell why, a note under the table
          says so.
        </p>
        <p>
          <span className="font-semibold text-ink">Foreign companies are the hardest.</span> Companies outside the US
          file Forms 20-F, 40-F and 6-K, which follow looser rules than a US 10-K or 10-Q. Many report every six months, or
          put out their quarterly results in untagged press releases. Their pages can have more gaps and quirks than a US
          company's.
        </p>
        <p>
          <span className="font-semibold text-ink">Written by free-tier AI.</span> The analysis runs on Google&apos;s
          lightweight Gemini models at no cost. Every figure and quote is checked against the filings, but a more capable
          model would write sharper, more complete analysis. This is a personal project, not a commercial product, so
          treat it as a starting point and read the original filing before relying on anything here.
        </p>
      </div>
    </section>
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

    // The AI analysis is written once per filing and then stored; ask for it only when it is missing.
    // The omission check runs after the summary; a summary without it (a spent quota) asks again.
    if ((data.insights?.status === 'ready' && data.insights?.audit) || !data.insights?.configured) return
    setInsightsRequest({ status: 'loading' })
    try {
      const updated = await postJson(`/api/research/${encodeURIComponent(ticker)}/insights`)
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

  const tabProps = { research: research.data, request: insightsRequest }
  return (
    <div className="flex min-h-screen flex-col bg-page">
      <SearchHeader query={query} onQueryChange={setQuery} onSubmit={runAnalysis} loading={loading} onHome={goHome} landing={idle} />

      <main className="mx-auto w-full max-w-6xl flex-1 px-5 py-10 sm:px-8 sm:py-12">
        {loading && (
          <LoadingState
            ticker={activeQuery}
            message={research.status === 'loading' ? RESEARCH_LOADING : writingInsights ? INSIGHTS_LOADING : undefined}
          />
        )}

        {failed && <FailureAlert query={activeQuery} message={summary.error} />}

        {idle && <EmptyState onPick={runAnalysis} query={query} onQueryChange={setQuery} />}

        {showPage && (
          <>
            <CompanyHeader data={header.data} subtitle={header.subtitle} onHome={goHome} />
            {researchReady ? (
              <>
                <Tabs tabs={TABS} active={tab} onChange={setTab} />
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
      </main>

      <footer className="mx-auto flex w-full max-w-6xl flex-col justify-between gap-2 border-t border-line px-5 py-6 text-[11px] text-muted sm:flex-row sm:px-8">
        <span>Source: SEC EDGAR · AI analysis: Google Gemini (free tier), checked against the filings · A personal project</span>
        <span>Research aid only. Review the original filing before making investment decisions.</span>
      </footer>
      <Analytics />
    </div>
  )
}
