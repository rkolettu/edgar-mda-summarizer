import { useState } from 'react'
import { Bar, BarChart, CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { AXIS_TICK, CHART_CHROME, SERIES } from '../lib/colors'
import { formatMoney, formatPct, formatSignedPct, formatUnit, periodLabel } from '../lib/format'
import { ChartCard, EmptyChart } from './ChartCard'
import { Legend, SeriesTooltip } from './TrendCharts'

const VIEWS = [
  { key: 'annual', label: 'Annual' },
  { key: 'quarterly', label: 'Quarterly' },
]

function Segmented({ value, onChange }) {
  return (
    <div role="radiogroup" aria-label="Period" className="inline-flex rounded-lg border border-line bg-panel p-0.5">
      {VIEWS.map((view) => (
        <button
          key={view.key}
          type="button"
          role="radio"
          aria-checked={value === view.key}
          onClick={() => onChange(view.key)}
          className={`rounded-md px-3 py-1.5 text-xs font-medium ${value === view.key ? 'bg-ink text-panel' : 'text-ink-2 hover:text-ink'}`}
        >
          {view.label}
        </button>
      ))}
    </div>
  )
}

function seriesRows(table, keys) {
  const rows = Object.fromEntries(table.rows.map((r) => [r.key, r]))
  return table.columns.map((column, i) => ({
    period: periodLabel(column.fiscal_year, column.fiscal_period),
    ...Object.fromEntries(keys.map((k) => [k, rows[k]?.values[i]?.v ?? null])),
  }))
}

export function RevenueCashChart({ table, currency }) {
  const series = [
    { key: 'revenue', label: 'Revenue', color: SERIES.blue },
    { key: 'free_cash_flow', label: 'Free cash flow', color: SERIES.aqua },
  ]
  const rows = seriesRows(table, series.map((s) => s.key))
  const present = series.filter((s) => rows.some((r) => r[s.key] != null))
  const money = (v) => formatMoney(v, currency)
  return (
    <ChartCard title="Revenue & free cash flow" subtitle={`${rows.length} periods · ${currency}`}>
      {present.length === 0 ? (
        <EmptyChart message="No revenue or cash flow reported" />
      ) : (
        <>
          <Legend series={present} />
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={rows} margin={{ top: 4, right: 4, bottom: 0, left: 0 }} barCategoryGap="22%" barGap={2}>
                <CartesianGrid vertical={false} stroke={CHART_CHROME.grid} />
                <XAxis dataKey="period" tick={AXIS_TICK} axisLine={{ stroke: CHART_CHROME.axis }} tickLine={false} interval={0} />
                <YAxis tickFormatter={(v) => formatMoney(v, currency, { digits: 0 })} tick={AXIS_TICK} axisLine={false} tickLine={false} width={64} />
                <ReferenceLine y={0} stroke={CHART_CHROME.axis} />
                <Tooltip cursor={{ fill: 'rgba(45,86,148,0.05)' }} content={<SeriesTooltip series={present} format={money} />} />
                {present.map((s) => (
                  <Bar key={s.key} dataKey={s.key} name={s.label} fill={s.color} radius={[4, 4, 0, 0]} maxBarSize={24} isAnimationActive={false} />
                ))}
              </BarChart>
            </ResponsiveContainer>
          </div>
        </>
      )}
    </ChartCard>
  )
}

export function MarginChart({ table }) {
  const series = [
    { key: 'gross_margin', label: 'Gross', color: SERIES.blue },
    { key: 'operating_margin', label: 'Operating', color: SERIES.orange },
    { key: 'net_margin', label: 'Net', color: SERIES.aqua },
  ]
  const rows = seriesRows(table, series.map((s) => s.key))
  const present = series.filter((s) => rows.some((r) => r[s.key] != null))
  return (
    <ChartCard title="Margins" subtitle={`${rows.length} periods`}>
      {present.length === 0 ? (
        <EmptyChart message="Margins need reported revenue" />
      ) : (
        <>
          <Legend series={present} />
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
                <CartesianGrid vertical={false} stroke={CHART_CHROME.grid} />
                <XAxis dataKey="period" tick={AXIS_TICK} axisLine={{ stroke: CHART_CHROME.axis }} tickLine={false} interval={0} padding={{ left: 12, right: 12 }} />
                <YAxis tickFormatter={(v) => formatPct(v, 0)} tick={AXIS_TICK} axisLine={false} tickLine={false} width={44} />
                <Tooltip cursor={{ stroke: CHART_CHROME.axis, strokeWidth: 1 }} content={<SeriesTooltip series={present} format={(v) => formatPct(v)} />} />
                {present.map((s) => (
                  <Line
                    key={s.key}
                    dataKey={s.key}
                    name={s.label}
                    stroke={s.color}
                    strokeWidth={2}
                    connectNulls
                    dot={{ r: 4, fill: s.color, stroke: CHART_CHROME.surface, strokeWidth: 2 }}
                    activeDot={{ r: 5, stroke: CHART_CHROME.surface, strokeWidth: 2 }}
                    isAnimationActive={false}
                  />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>
        </>
      )}
    </ChartCard>
  )
}

function Cell({ cell, unit, currency }) {
  if (!cell) return <span className="text-muted">—</span>
  const text = formatUnit(cell.v, unit, currency)
  if (!cell.derived || unit !== 'currency') return text
  return (
    <span title="Calculated from reported figures">
      {text}
      <span className="text-muted">*</span>
    </span>
  )
}

function FinancialTable({ table, currency }) {
  const groups = []
  for (const row of table.rows) {
    if (groups.at(-1)?.name !== row.group) groups.push({ name: row.group, rows: [] })
    groups.at(-1).rows.push(row)
  }
  return (
    <section className="editorial-card overflow-hidden rounded-2xl border border-line bg-panel">
      <div className="relative overflow-x-auto">
        <table className="w-full min-w-[640px] border-collapse text-sm">
          <caption className="sr-only">Financial statements by period, in {currency}</caption>
          <thead>
            <tr className="border-b border-line text-[11px] font-semibold tracking-[0.08em] text-muted uppercase">
              <th scope="col" className="sticky left-0 bg-panel px-5 py-3 text-left font-semibold sm:px-6">Metric</th>
              {table.columns.map((c) => (
                <th key={`${c.fiscal_year}-${c.fiscal_period}`} scope="col" className="px-3 py-3 text-right font-semibold whitespace-nowrap last:pr-5 sm:last:pr-6">
                  {periodLabel(c.fiscal_year, c.fiscal_period)}
                </th>
              ))}
            </tr>
          </thead>
          {groups.map((group) => (
            <tbody key={group.name} className="border-b border-line last:border-b-0">
              <tr>
                <th colSpan={table.columns.length + 1} scope="colgroup" className="sticky left-0 bg-panel-2 px-5 py-2 text-left text-[11px] font-semibold tracking-[0.12em] text-muted uppercase sm:px-6">
                  {group.name}
                </th>
              </tr>
              {group.rows.map((row) => {
                const secondary = row.unit !== 'currency' && row.unit !== 'currency_per_share'
                return (
                  <tr key={row.key} className="border-t border-line/60 hover:bg-panel-2/60">
                    <th scope="row" className={`sticky left-0 bg-panel px-5 py-2 text-left font-normal whitespace-nowrap sm:px-6 ${secondary ? 'text-ink-2' : 'text-ink'}`}>
                      {row.label}
                    </th>
                    {row.values.map((cell, i) => (
                      <td key={i} className={`px-3 py-2 text-right font-mono tabular-nums whitespace-nowrap last:pr-5 sm:last:pr-6 ${secondary ? 'text-ink-2' : 'text-ink'}`}>
                        <Cell cell={cell} unit={row.unit} currency={currency} />
                      </td>
                    ))}
                  </tr>
                )
              })}
            </tbody>
          ))}
        </table>
      </div>
      <footer className="border-t border-line px-5 py-3 text-[11px] leading-relaxed text-muted sm:px-6">
        From the company's XBRL-tagged filings, in {currency}; restated figures replace earlier ones. * Calculated from reported
        figures: free cash flow is operating cash flow minus capital expenditures, and quarters not reported on their own are
        year-to-date totals minus earlier quarters. Growth compares the same period a year earlier.
      </footer>
    </section>
  )
}

function Breakdowns({ breakdowns, view, currency }) {
  const panels = breakdowns.map((b) => ({ ...b, data: b[view] })).filter((b) => b.data?.items?.length)
  if (!panels.length) return null
  return (
    <div className="mt-10">
      <div className="mb-4 flex items-end justify-between border-b border-line pb-3">
        <h2 className="text-xl font-semibold tracking-[-0.03em] text-ink">Where revenue comes from</h2>
      </div>
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        {panels.map((panel) => (
          <section key={panel.family} className="editorial-card overflow-hidden rounded-2xl border border-line bg-panel">
            <header className="flex items-center justify-between gap-3 border-b border-line px-5 py-4 sm:px-6">
              <h3 className="text-base font-semibold tracking-[-0.025em] text-ink">{panel.label}</h3>
              <span className="text-xs text-muted">{panel.data.label}</span>
            </header>
            <table className="w-full text-sm">
              <thead className="text-[11px] font-semibold tracking-[0.08em] text-muted uppercase">
                <tr>
                  <th scope="col" className="px-5 py-2 text-left font-semibold sm:px-6">Line</th>
                  <th scope="col" className="px-3 py-2 text-right font-semibold">Amount</th>
                  <th scope="col" className="px-3 py-2 text-right font-semibold">YoY</th>
                  <th scope="col" className="px-5 py-2 text-right font-semibold sm:px-6">Share</th>
                </tr>
              </thead>
              <tbody>
                {panel.data.items.map((item) => (
                  <tr key={item.key} className="border-t border-line/60">
                    <th scope="row" className="px-5 py-2 text-left font-normal text-ink sm:px-6">{item.label}</th>
                    <td className="px-3 py-2 text-right font-mono text-ink tabular-nums">{formatMoney(item.value, currency)}</td>
                    <td className="px-3 py-2 text-right font-mono text-ink-2 tabular-nums">{item.growth == null ? '—' : formatSignedPct(item.growth)}</td>
                    <td className="px-5 py-2 text-right font-mono text-ink-2 tabular-nums sm:px-6">{item.share_of_revenue == null ? '—' : formatPct(item.share_of_revenue)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <footer className="border-t border-line px-5 py-3 text-[11px] leading-relaxed text-muted sm:px-6">
              As tagged by the company, {panel.data.label}. Lines can overlap when the filing reports a total and its parts.
            </footer>
          </section>
        ))}
      </div>
    </div>
  )
}

export default function FinancialsTab({ research }) {
  const [view, setView] = useState('annual')
  const { financials } = research
  const currency = financials.currency ?? 'USD'
  const table = financials[view]
  const empty = !table?.rows?.length

  return (
    <div>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3 border-b border-line pb-3">
        <div>
          <p className="mb-1 text-[11px] font-semibold tracking-[0.14em] text-muted uppercase">Reported financials</p>
          <h2 className="text-2xl font-semibold tracking-[-0.04em] text-ink">Financial trends</h2>
        </div>
        <Segmented value={view} onChange={setView} />
      </div>
      {empty ? (
        <p className="rounded-xl border border-line bg-panel px-5 py-5 text-sm text-muted">
          No {view} figures are tagged in this company's stored filings.
        </p>
      ) : (
        <>
          <div className="mb-8 grid grid-cols-1 gap-5 lg:grid-cols-2">
            <RevenueCashChart table={table} currency={currency} />
            <MarginChart table={table} />
          </div>
          <FinancialTable table={table} currency={currency} />
          <Breakdowns breakdowns={financials.breakdowns ?? []} view={view} currency={currency} />
        </>
      )}
    </div>
  )
}
