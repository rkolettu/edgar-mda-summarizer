import { Bar, BarChart, CartesianGrid, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { CHART_CHROME, SERIES } from '../lib/colors'
import { formatUsd } from '../lib/format'
import { ChartCard, ChartTooltip, EmptyChart } from './ChartCard'

const ROW_HEIGHT = 44

const SOURCE_NOTES = {
  xbrl: 'Source: cash flow statement and income statement (XBRL), latest fiscal year.',
  gemini: 'Source: extracted from the MD&A text by Gemini; no XBRL figures were available.',
}

export default function CapitalDeploymentChart({ data, source }) {
  const rows = data.filter((d) => d.value > 0).sort((a, b) => b.value - a.value)
  const height = rows.length * ROW_HEIGHT + 32

  return (
    <ChartCard title="Capital deployment" subtitle="USD" footer={SOURCE_NOTES[source]}>
      {rows.length === 0 ? (
        <EmptyChart message="No capital deployment figures disclosed" />
      ) : (
        <>
          <div className="space-y-4 sm:hidden">
            {rows.map((row) => (
              <div key={row.name}>
                <div className="mb-1.5 flex items-baseline justify-between gap-3 text-xs">
                  <span className="text-ink-2">{row.name}</span>
                  <span className="font-mono text-ink tabular-nums">{formatUsd(row.value)}</span>
                </div>
                <div className="h-2 rounded-full bg-panel-2" aria-hidden="true">
                  <div className="h-full rounded-full bg-accent" style={{ width: `${(row.value / rows[0].value) * 100}%` }} />
                </div>
              </div>
            ))}
          </div>
          <div className="hidden sm:block" style={{ height }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={rows} layout="vertical" margin={{ top: 0, right: 56, bottom: 0, left: 0 }} barCategoryGap={10}>
                <CartesianGrid horizontal={false} stroke={CHART_CHROME.grid} />
                <XAxis
                  type="number"
                  tickFormatter={(v) => formatUsd(v, { digits: 0 })}
                  tick={{ fill: CHART_CHROME.tick, fontSize: 11 }}
                  axisLine={{ stroke: CHART_CHROME.axis }}
                  tickLine={false}
                />
                <YAxis
                  type="category"
                  dataKey="name"
                  width={132}
                  tick={{ fill: CHART_CHROME.label, fontSize: 12 }}
                  axisLine={false}
                  tickLine={false}
                />
                <Tooltip
                  cursor={{ fill: 'rgba(45,86,148,0.05)' }}
                  content={<ChartTooltip formatValue={formatUsd} />}
                />
                <Bar dataKey="value" fill={SERIES.blue} radius={[0, 4, 4, 0]} maxBarSize={22} isAnimationActive={false}>
                  <LabelList
                    dataKey="value"
                    position="right"
                    formatter={formatUsd}
                    style={{ fill: '#575650', fontSize: 12, fontFamily: 'var(--font-mono)' }}
                  />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </>
      )}
    </ChartCard>
  )
}
