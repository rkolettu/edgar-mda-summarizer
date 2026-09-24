import { ChartPie, CircleAlert, CircleCheck } from 'lucide-react'
import { useState } from 'react'
import { Cell, Pie, PieChart, ResponsiveContainer } from 'recharts'
import { STATUS } from '../lib/colors'
import { formatShare, formatSignedPct, formatUsd } from '../lib/format'
import { ChartCard, EmptyChart } from './ChartCard'

// Order validated for CVD + normal-vision separation on the panel surface, including the donut's wrap-around pair.
const SEGMENT_COLORS = ['#3987e5', '#199e70', '#9085e9', '#c98500', '#d55181']
const OTHER_COLOR = '#5b6675'
const PANEL_SURFACE = '#11161d'

function toSegments(raw) {
  const sorted = raw.filter((d) => d.value > 0).sort((a, b) => b.value - a.value)
  if (sorted.length <= SEGMENT_COLORS.length + 1) {
    return sorted.map((d, i) => ({ ...d, color: SEGMENT_COLORS[i] ?? OTHER_COLOR }))
  }
  const head = sorted.slice(0, SEGMENT_COLORS.length).map((d, i) => ({ ...d, color: SEGMENT_COLORS[i] }))
  const otherValue = sorted.slice(SEGMENT_COLORS.length).reduce((sum, d) => sum + d.value, 0)
  return [...head, { name: 'Other', value: otherValue, color: OTHER_COLOR }]
}

function ReconciliationNote({ check }) {
  if (!check) return 'Segments extracted from the MD&A by Gemini; no XBRL revenue to reconcile against.'
  const Icon = check.reconciles ? CircleCheck : CircleAlert
  return (
    <span className="flex items-start gap-1.5">
      <Icon size={13} className="mt-px shrink-0" style={{ color: check.reconciles ? STATUS.good : STATUS.warning }} aria-hidden />
      <span>
        {check.reconciles
          ? `Segments reconcile to reported revenue of ${formatUsd(check.reported_revenue)} (${formatSignedPct(check.difference)}).`
          : `Segments sum to ${formatUsd(check.segments_total)} vs. reported revenue of ${formatUsd(check.reported_revenue)} (${formatSignedPct(check.difference)}). The breakdown may omit segments or mix product and geographic views.`}
      </span>
    </span>
  )
}

export default function RevenueMixChart({ data, check }) {
  const [active, setActive] = useState(null)
  const segments = toSegments(data)
  const total = segments.reduce((sum, d) => sum + d.value, 0)
  const focus = active === null ? null : segments[active]

  return (
    <ChartCard title="Revenue Mix" subtitle="USD" icon={ChartPie} footer={<ReconciliationNote check={check} />}>
      {segments.length === 0 ? (
        <EmptyChart message="No segment revenue disclosed" />
      ) : (
        <>
          <div className="relative h-60">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={segments}
                  dataKey="value"
                  nameKey="name"
                  innerRadius="64%"
                  outerRadius="92%"
                  startAngle={90}
                  endAngle={-270}
                  stroke={PANEL_SURFACE}
                  strokeWidth={2}
                  isAnimationActive={false}
                  onMouseEnter={(_, i) => setActive(i)}
                  onMouseLeave={() => setActive(null)}
                >
                  {segments.map((d, i) => (
                    <Cell
                      key={d.name}
                      fill={d.color}
                      fillOpacity={active === null || active === i ? 1 : 0.3}
                      className="cursor-pointer transition-[fill-opacity]"
                    />
                  ))}
                </Pie>
              </PieChart>
            </ResponsiveContainer>
            <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center px-16 text-center">
              {focus ? (
                <>
                  <span className="max-w-[9rem] truncate text-[11px] tracking-wide text-ink-2 uppercase">
                    {focus.name}
                  </span>
                  <span className="text-xl font-semibold text-ink">{formatUsd(focus.value)}</span>
                  <span className="font-mono text-xs text-muted">{formatShare(focus.value, total)} of total</span>
                </>
              ) : (
                <>
                  <span className="text-xl font-semibold text-ink">{formatUsd(total)}</span>
                  <span className="text-[11px] tracking-wide text-muted uppercase">Total</span>
                </>
              )}
            </div>
          </div>

          <table className="mt-4 w-full text-sm">
            <caption className="sr-only">Revenue by segment</caption>
            <tbody>
              {segments.map((d, i) => (
                <tr
                  key={d.name}
                  onMouseEnter={() => setActive(i)}
                  onMouseLeave={() => setActive(null)}
                  className={`border-t border-line transition-colors first:border-t-0 ${active === i ? 'bg-panel-2' : ''}`}
                >
                  <td className="py-2 pr-2 pl-1">
                    <span className="flex items-center gap-2.5">
                      <span className="h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: d.color }} />
                      <span className="text-ink-2">{d.name}</span>
                    </span>
                  </td>
                  <td className="py-2 text-right font-mono text-ink tabular-nums">{formatUsd(d.value)}</td>
                  <td className="w-16 py-2 pr-1 text-right font-mono text-muted tabular-nums">
                    {formatShare(d.value, total)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </ChartCard>
  )
}
