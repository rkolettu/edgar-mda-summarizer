import { ArrowRight } from 'lucide-react'
import { formatPct, formatSignedPct, formatUnit, periodLabel } from '../lib/format'
import { Delta, Tile } from './KpiStrip'
import { MarginChart, RevenueCashChart } from './FinancialsTab'
import { AiLabel, Card, InsightsNotice, SectionHeader, SynthPoint } from './Insights'

function latest(table, key) {
  const row = table?.rows?.find((r) => r.key === key)
  if (!row) return null
  for (let i = row.values.length - 1; i >= 0; i--) {
    if (row.values[i]) return { value: row.values[i].v, column: table.columns[i] }
  }
  return null
}

function Kpis({ financials }) {
  const { annual, quarterly, currency } = financials
  const cell = (table, key) => latest(table, key)
  const money = (v) => formatUnit(v, 'currency', currency)
  const revenue = cell(annual, 'revenue')
  const quarter = cell(quarterly, 'revenue')
  const fcf = cell(annual, 'free_cash_flow')
  const netCash = cell(quarterly, 'net_cash') ?? cell(annual, 'net_cash')
  const label = (c) => (c ? periodLabel(c.column.fiscal_year, c.column.fiscal_period) : '')
  const tiles = [
    revenue && { label: `Revenue · ${label(revenue)}`, value: money(revenue.value), sub: <Delta value={cell(annual, 'revenue_growth')?.value} /> },
    quarter && { label: `Revenue · ${label(quarter)}`, value: money(quarter.value), sub: <Delta value={cell(quarterly, 'revenue_growth')?.value} /> },
    cell(annual, 'operating_margin') && {
      label: 'Operating margin', value: formatPct(cell(annual, 'operating_margin').value),
      sub: cell(annual, 'net_margin') ? `Net margin ${formatPct(cell(annual, 'net_margin').value)}` : null,
    },
    fcf && { label: 'Free cash flow', value: money(fcf.value), sub: `${label(fcf)}${cell(annual, 'fcf_margin') ? ` · ${formatPct(cell(annual, 'fcf_margin').value)} of revenue` : ''}` },
    netCash && { label: 'Net cash (debt)', value: money(netCash.value), sub: `as of ${label(netCash)}` },
    cell(annual, 'eps_diluted') && { label: 'Diluted EPS', value: formatUnit(cell(annual, 'eps_diluted').value, 'currency_per_share', currency), sub: <Delta value={cell(annual, 'eps_growth')?.value} /> },
  ].filter(Boolean)
  if (!tiles.length) return null
  return (
    <section aria-label="Key financials" className="mb-8">
      <div className="grid grid-cols-2 border-t border-line md:grid-cols-3 xl:grid-cols-6">
        {tiles.map((t) => <Tile key={t.label} {...t} />)}
      </div>
      <p className="mt-3 text-[11px] text-muted">From the XBRL data tagged in the company&apos;s filings; growth is year over year.</p>
    </section>
  )
}

function changeLine(item) {
  if (item.kind === 'narrative') return item.category_label
  if (item.change === null || item.change === undefined) return `${item.change_type === 'new' ? 'New' : 'Changed'} · ${item.category_label}`
  const moved = item.unit === 'currency' ? formatSignedPct(item.change) : `${item.change > 0 ? '+' : ''}${(item.change * 100).toFixed(1)} pts`
  return `${moved} · ${item.category_label}`
}

function TopChanges({ changes, onNavigate }) {
  const items = (changes?.items ?? []).slice(0, 4)
  if (!items.length) return null
  return (
    <Card
      title={`Largest changes in the ${changes.filing.fiscal_label} ${changes.filing.form}`}
      aside={(
        <button type="button" onClick={() => onNavigate('changes')} className="inline-flex items-center gap-1 text-xs font-medium text-accent hover:text-accent-hover">
          All filing changes <ArrowRight size={12} aria-hidden />
        </button>
      )}
    >
      <ul className="divide-y divide-line">
        {items.map((item, i) => (
          <li key={i} className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 px-5 py-3 sm:px-6">
            <span className="text-sm text-ink">{item.label}</span>
            <span className="font-mono text-xs text-ink-2 tabular-nums">
              {item.kind === 'numeric' && item.value !== null ? `${formatUnit(item.value, item.unit === 'points' ? 'ratio' : item.unit, item.currency)} · ` : ''}
              {changeLine(item)}
            </span>
          </li>
        ))}
      </ul>
    </Card>
  )
}

export default function OverviewTab({ research, request, onNavigate }) {
  const { insights, financials } = research
  const takeaways = insights?.takeaways ?? []
  const overview = insights?.business?.overview?.text || insights?.business?.summary
  return (
    <div>
      <InsightsNotice insights={insights} request={request} />
      {takeaways.length > 0 && (
        <>
          <SectionHeader eyebrow="Latest filing" title="Key takeaways" aside={<AiLabel insights={insights} />}>
            Written from the stored financials, filing changes and quoted filing text. Each point names the facts it rests on, and every figure is
            checked against them.
          </SectionHeader>
          <Card className="mb-8">
            <ol className="divide-y divide-line">
              {takeaways.map((item, i) => (
                <li key={i} className="px-5 py-5 sm:px-6"><SynthPoint item={item} /></li>
              ))}
            </ol>
          </Card>
        </>
      )}
      <Kpis financials={financials} />
      {overview && (
        <Card className="mb-8" title="What the company does" aside={(
          <button type="button" onClick={() => onNavigate('business')} className="inline-flex items-center gap-1 text-xs font-medium text-accent hover:text-accent-hover">
            Business &amp; strategy <ArrowRight size={12} aria-hidden />
          </button>
        )}>
          <p className="px-5 py-4 text-sm leading-relaxed text-ink-2 sm:px-6">{overview}</p>
        </Card>
      )}
      <div className="mb-8">
        <TopChanges changes={research.changes} onNavigate={onNavigate} />
      </div>
      {financials.annual?.rows?.length > 0 && (
        <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
          <RevenueCashChart table={financials.annual} currency={financials.currency ?? 'USD'} />
          <MarginChart table={financials.annual} />
        </div>
      )}
    </div>
  )
}
