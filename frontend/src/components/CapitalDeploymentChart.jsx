import { ChartBar } from 'lucide-react'
import { Bar, BarChart, CartesianGrid, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { formatBillions } from '../lib/format'
import { ChartCard, ChartTooltip, EmptyChart } from './ChartCard'

const BAR_COLOR = '#3987e5'
const ROW_HEIGHT = 44

export default function CapitalDeploymentChart({ data }) {
  const rows = data.filter((d) => d.value > 0).sort((a, b) => b.value - a.value)
  const height = rows.length * ROW_HEIGHT + 32

  return (
    <ChartCard title="Capital Deployment" subtitle="USD" icon={ChartBar}>
      {rows.length === 0 ? (
        <EmptyChart message="No capital deployment figures disclosed" />
      ) : (
        <div style={{ height }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={rows} layout="vertical" margin={{ top: 0, right: 56, bottom: 0, left: 0 }} barCategoryGap={10}>
              <CartesianGrid horizontal={false} stroke="#1f2630" />
              <XAxis
                type="number"
                tickFormatter={formatBillions}
                tick={{ fill: '#6b7684', fontSize: 11 }}
                axisLine={{ stroke: '#2a323e' }}
                tickLine={false}
              />
              <YAxis
                type="category"
                dataKey="name"
                width={132}
                tick={{ fill: '#aab3c0', fontSize: 12 }}
                axisLine={false}
                tickLine={false}
              />
              <Tooltip
                cursor={{ fill: 'rgba(255,255,255,0.04)' }}
                content={<ChartTooltip formatValue={formatBillions} />}
              />
              <Bar dataKey="value" fill={BAR_COLOR} radius={[0, 4, 4, 0]} maxBarSize={22} isAnimationActive={false}>
                <LabelList
                  dataKey="value"
                  position="right"
                  formatter={formatBillions}
                  style={{ fill: '#ffffff', fontSize: 12, fontFamily: 'var(--font-mono)' }}
                />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </ChartCard>
  )
}
