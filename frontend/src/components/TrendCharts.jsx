import { ChartColumn, ChartLine } from 'lucide-react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { CHART_CHROME, SERIES } from '../lib/colors'
import { fiscalYearLabel, formatPct, formatUsd } from '../lib/format'
import { ChartCard, EmptyChart } from './ChartCard'

const AXIS_TICK = { fill: CHART_CHROME.tick, fontSize: 11 }

function Legend({ series }) {
  return (
    <ul className="mb-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-2">
      {series.map((s) => (
        <li key={s.key} className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-sm" style={{ background: s.color }} aria-hidden />
          {s.label}
        </li>
      ))}
    </ul>
  )
}

function SeriesTooltip({ active, payload, label, series, format }) {
  if (!active || !payload?.length) return null
  const row = payload[0].payload
  return (
    <div className="rounded-md border border-line bg-panel-2 px-3 py-2 text-xs shadow-xl shadow-black/40">
      <div className="mb-1 font-medium text-ink">{label}</div>
      {series.map((s) => (
        <div key={s.key} className="flex items-center justify-between gap-4">
          <span className="flex items-center gap-1.5 text-ink-2">
            <span className="h-2 w-2 rounded-sm" style={{ background: s.color }} aria-hidden />
            {s.label}
          </span>
          <span className="font-mono text-ink tabular-nums">{format(row[s.key])}</span>
        </div>
      ))}
    </div>
  )
}

function toRows(years, keys) {
  return years.map((y) => ({ fy: fiscalYearLabel(y.period_end), ...Object.fromEntries(keys.map((k) => [k, y[k]])) }))
}

export function RevenueFcfChart({ years }) {
  const series = [
    { key: 'revenue', label: 'Revenue', color: SERIES.blue },
    { key: 'free_cash_flow', label: 'Free Cash Flow', color: SERIES.aqua },
  ].filter((s) => years.some((y) => y[s.key] != null))
  const rows = toRows(years, series.map((s) => s.key))

  return (
    <ChartCard title="Revenue & Free Cash Flow" subtitle={`${years.length}-year trend`} icon={ChartColumn}>
      {series.length === 0 ? (
        <EmptyChart message="No revenue or cash flow data reported" />
      ) : (
        <>
          <Legend series={series} />
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={rows} margin={{ top: 4, right: 4, bottom: 0, left: 0 }} barCategoryGap="22%" barGap={2}>
                <CartesianGrid vertical={false} stroke={CHART_CHROME.grid} />
                <XAxis dataKey="fy" tick={AXIS_TICK} axisLine={{ stroke: CHART_CHROME.axis }} tickLine={false} />
                <YAxis tickFormatter={(v) => formatUsd(v, { digits: 0 })} tick={AXIS_TICK} axisLine={false} tickLine={false} width={56} />
                <ReferenceLine y={0} stroke={CHART_CHROME.axis} />
                <Tooltip cursor={{ fill: 'rgba(255,255,255,0.04)' }} content={<SeriesTooltip series={series} format={formatUsd} />} />
                {series.map((s) => (
                  <Bar key={s.key} dataKey={s.key} name={s.label} fill={s.color} radius={[4, 4, 0, 0]} maxBarSize={28} isAnimationActive={false} />
                ))}
              </BarChart>
            </ResponsiveContainer>
          </div>
        </>
      )}
    </ChartCard>
  )
}

export function MarginsChart({ years }) {
  const withMargins = years.map((y) => ({
    ...y,
    gross_margin: y.revenue && y.gross_profit != null ? y.gross_profit / y.revenue : null,
    operating_margin: y.revenue && y.operating_income != null ? y.operating_income / y.revenue : null,
    net_margin: y.revenue && y.net_income != null ? y.net_income / y.revenue : null,
  }))
  const series = [
    { key: 'gross_margin', label: 'Gross', color: SERIES.blue },
    { key: 'operating_margin', label: 'Operating', color: SERIES.orange },
    { key: 'net_margin', label: 'Net', color: SERIES.aqua },
  ].filter((s) => withMargins.some((y) => y[s.key] != null))
  const rows = toRows(withMargins, series.map((s) => s.key))

  return (
    <ChartCard title="Margins" subtitle={`${years.length}-year trend`} icon={ChartLine}>
      {series.length === 0 ? (
        <EmptyChart message="Margins need reported revenue" />
      ) : (
        <>
          <Legend series={series} />
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
                <CartesianGrid vertical={false} stroke={CHART_CHROME.grid} />
                <XAxis dataKey="fy" tick={AXIS_TICK} axisLine={{ stroke: CHART_CHROME.axis }} tickLine={false} padding={{ left: 12, right: 12 }} />
                <YAxis tickFormatter={(v) => formatPct(v, 0)} tick={AXIS_TICK} axisLine={false} tickLine={false} width={44} />
                <Tooltip
                  cursor={{ stroke: CHART_CHROME.axis, strokeWidth: 1 }}
                  content={<SeriesTooltip series={series} format={(v) => formatPct(v)} />}
                />
                {series.map((s) => (
                  <Line
                    key={s.key}
                    dataKey={s.key}
                    name={s.label}
                    stroke={s.color}
                    strokeWidth={2}
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
