import { ArrowDownRight, ArrowUpRight, MoveHorizontal } from 'lucide-react'
import { formatPct, formatUnit } from '../lib/format'
import { AiLabel, Badge, Card, InsightsNotice, QuotedList, SectionHeader } from './Insights'
import { FigureText } from './Verification'

const DIRECTION = {
  up: { label: 'Up', icon: ArrowUpRight },
  down: { label: 'Down', icon: ArrowDownRight },
  mixed: { label: 'Mixed', icon: MoveHorizontal },
}

// Segment revenue from the filings' tags, next to how the filing describes each segment.
function SegmentRevenue({ breakdowns, currency }) {
  const segments = breakdowns?.find((b) => b.family === 'segment')
  const view = segments?.annual ?? segments?.quarterly
  const items = (view?.items ?? []).filter((i) => i.metric === 'revenue')
  if (!items.length) return null
  return (
    <div className="border-b border-line px-5 py-4 sm:px-6">
      <p className="mb-2 text-[11px] font-semibold tracking-[0.08em] text-muted uppercase">Segment revenue · {view.label}</p>
      <ul className="flex flex-wrap gap-x-6 gap-y-2">
        {items.map((i) => (
          <li key={i.key} className="text-sm">
            <span className="text-ink">{i.label}</span>{' '}
            <span className="font-mono text-ink-2 tabular-nums">{formatUnit(i.value, 'currency', currency)}</span>
            {i.share_of_revenue != null && <span className="text-xs text-muted"> · {formatPct(i.share_of_revenue, 0)} of revenue</span>}
          </li>
        ))}
      </ul>
    </div>
  )
}

export default function BusinessTab({ research, request }) {
  const { insights, financials } = research
  const business = insights?.business
  const ready = insights && insights.status !== 'pending'
  const period = business?.drivers?.[0]?.source
  return (
    <div>
      <SectionHeader eyebrow="From the business description and management's discussion" title="Business & strategy" aside={<AiLabel insights={insights} />}>
        What the company does, where it says it is investing, and how management explains its results and outlook, in management&apos;s own
        terms. Every item quotes the filing it came from; quotes that cannot be found verbatim are hidden.
      </SectionHeader>
      <InsightsNotice insights={insights} request={request} />
      {!ready ? (
        <Card title="Segments"><SegmentRevenue breakdowns={financials.breakdowns} currency={financials.currency} /></Card>
      ) : (
        <div className="space-y-5">
          {(business.overview?.text || business.summary) && (
            <Card title="Overview">
              <div className="space-y-2 px-5 py-4 text-sm leading-relaxed text-ink-2 sm:px-6">
                {business.overview?.text && <p><FigureText text={business.overview.text} spans={business.overview.figures} /></p>}
                {business.summary && business.summary !== business.overview?.text && <p>{business.summary}</p>}
              </div>
            </Card>
          )}
          <Card title="Segments and products">
            <SegmentRevenue breakdowns={financials.breakdowns} currency={financials.currency} />
            <QuotedList items={business.segments} empty="The filing's business description was not available to read." />
          </Card>
          <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
            <Card title="Strategy and priorities">
              <QuotedList items={business.strategy} empty="No stated priorities were found." />
            </Card>
            <Card title="Outlook" aside={<span className="text-xs text-muted">Forward-looking; management&apos;s words</span>}>
              <QuotedList items={business.outlook} empty="No forward-looking statements were found." />
            </Card>
          </div>
          <Card title={`What moved the results${period ? ` · ${period.fiscal_label} ${period.form}` : ''}`}>
            <QuotedList
              items={business.drivers}
              empty="Management's explanation of the period was not available."
              badges={(item) => {
                const d = DIRECTION[item.direction] ?? DIRECTION.mixed
                return <Badge icon={d.icon}>{d.label}</Badge>
              }}
            />
          </Card>
          <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
            <Card title="Opportunities management describes">
              <QuotedList items={business.upside} empty="None stated." />
            </Card>
            <Card title="Cautions management describes">
              <QuotedList items={business.downside} empty="None stated." />
            </Card>
          </div>
        </div>
      )}
    </div>
  )
}
