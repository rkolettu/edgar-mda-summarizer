import { ExternalLink } from 'lucide-react'
import { formatEps, formatUsd } from '../lib/format'
import { Evidence } from './AnalysisSection'
import { Delta, Tile } from './KpiStrip'

function quarterLabel(metrics, reportDate) {
  if (metrics?.fiscal_period && metrics?.fiscal_year) return `${metrics.fiscal_period} FY${metrics.fiscal_year}`
  return `Quarter ended ${reportDate}`
}

export default function LatestQuarter({ quarter }) {
  const { filing, metrics, highlights } = quarter
  const tiles = metrics
    ? [
        { key: 'revenue', label: 'Revenue', value: formatUsd(metrics.revenue), growth: metrics.revenue_growth },
        { key: 'net_income', label: 'Net Income', value: formatUsd(metrics.net_income), growth: metrics.net_income_growth },
        { key: 'eps_diluted', label: 'Diluted EPS', value: formatEps(metrics.eps_diluted), growth: metrics.eps_diluted_growth },
      ].filter((t) => metrics[t.key] != null)
    : []

  return (
    <section className="editorial-card mb-10 overflow-hidden rounded-2xl border border-line bg-panel">
      <header className="flex flex-wrap items-center gap-x-2.5 gap-y-1 border-b border-line px-5 py-4 sm:px-6">
        <h2 className="text-base font-semibold tracking-[-0.025em] text-ink">
          Latest quarter · {quarterLabel(metrics, filing.report_date)}
        </h2>
        <span className="text-xs text-muted">
          10-Q for the quarter ended {filing.report_date}, filed {filing.filing_date}
        </span>
        <a
          href={filing.document_url}
          target="_blank"
          rel="noreferrer"
          className="ml-auto flex items-center gap-1 text-xs text-accent hover:text-accent-hover"
        >
          View 10-Q <ExternalLink size={11} />
        </a>
      </header>

      <div className="grid grid-cols-1 gap-5 p-5 sm:p-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
        {tiles.length ? (
          <div className="grid grid-cols-1 self-start border-t border-line sm:grid-cols-3 lg:grid-cols-1">
            {tiles.map((t) => (
              <Tile key={t.key} label={t.label} value={t.value} sub={<Delta value={t.growth} />} />
            ))}
          </div>
        ) : (
          <p className="text-sm text-muted">No quarterly XBRL figures reported for this period.</p>
        )}

        <ol className="space-y-4">
          {highlights.map((h, i) => (
            <li key={i}>
              <h3 className="text-[15px] leading-snug font-semibold text-ink">{h.headline}</h3>
              <p className="mt-1.5 text-sm leading-relaxed text-ink-2">{h.detail}</p>
              <Evidence quote={h.evidence} verified={h.verified} where="10-Q" />
            </li>
          ))}
        </ol>
      </div>
    </section>
  )
}
