import { ArrowDownRight, ArrowUpRight } from 'lucide-react'
import { STATUS } from '../lib/colors'
import { fiscalYearLabel, formatEps, formatPct, formatSignedPct, formatUsd } from '../lib/format'

export function Delta({ value, suffix = 'YoY' }) {
  if (value === null || value === undefined) return null
  const up = value >= 0
  const Icon = up ? ArrowUpRight : ArrowDownRight
  return (
    <span className="inline-flex items-center gap-0.5 font-mono text-xs" style={{ color: up ? STATUS.good : STATUS.critical }}>
      <Icon size={13} aria-hidden />
      {formatSignedPct(value)} <span className="text-muted">{suffix}</span>
    </span>
  )
}

export function Tile({ label, value, sub }) {
  return (
    <div className="min-w-0 border-b border-line px-3 py-5 sm:px-4">
      <div className="truncate text-[11px] font-semibold tracking-[0.08em] text-muted uppercase">{label}</div>
      <div className="mt-2 truncate text-2xl font-semibold tracking-[-0.04em] text-ink">{value}</div>
      <div className="mt-1 min-h-4 truncate text-xs text-ink-2">{sub}</div>
    </div>
  )
}

export default function KpiStrip({ kpis }) {
  const fy = fiscalYearLabel(kpis.period_end)
  const tiles = [
    { label: `Revenue · ${fy}`, value: formatUsd(kpis.revenue), sub: <Delta value={kpis.revenue_growth} /> },
    { label: 'Gross Margin', value: formatPct(kpis.gross_margin), sub: kpis.gross_margin == null ? 'Not reported' : null },
    { label: 'Operating Margin', value: formatPct(kpis.operating_margin), sub: kpis.net_margin != null ? `Net margin ${formatPct(kpis.net_margin)}` : null },
    { label: 'Free Cash Flow', value: formatUsd(kpis.free_cash_flow), sub: kpis.fcf_margin != null ? `${formatPct(kpis.fcf_margin)} of revenue` : null },
    { label: 'Diluted EPS', value: formatEps(kpis.eps_diluted), sub: <Delta value={kpis.eps_growth} /> },
    { label: 'Buybacks + divs', value: formatUsd(kpis.shareholder_returns), sub: kpis.cash != null ? `Cash ${formatUsd(kpis.cash)}` : null },
  ]

  return (
    <section aria-label="Key financials" className="mb-6">
      <div className="grid grid-cols-2 border-t border-line md:grid-cols-3 xl:grid-cols-6">
        {tiles.map((t) => (
          <Tile key={t.label} {...t} />
        ))}
      </div>
      <p className="mt-3 text-[11px] text-muted">Source: XBRL financial data filed with the SEC.</p>
    </section>
  )
}
