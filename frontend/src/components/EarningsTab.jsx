import { ExternalLink } from 'lucide-react'
import { formatPct, formatUnit, periodLabel } from '../lib/format'
import { AiLabel, Card, InsightsNotice, QuotedList, SectionHeader, SynthPoint } from './Insights'
import { FigureText } from './Verification'

const BRIDGE_ROWS = [
  ['operating_income', 'Operating income'],
  ['non_operating', 'Non-operating income (expense)'],
  ['pretax_income', 'Income before taxes'],
  ['income_tax', 'Income tax'],
  ['net_income', 'Net income'],
]

function Bridge({ bridge, currency }) {
  const money = (v) => formatUnit(v, 'currency', currency)
  return (
    <Card title={`Operating income to net income · ${bridge.label}`}>
      <table className="w-full border-collapse text-sm">
        <caption className="sr-only">Earnings bridge for {bridge.label}</caption>
        <tbody>
          {BRIDGE_ROWS.map(([key, label]) => (
            <tr key={key} className={`border-t border-line/60 first:border-t-0 ${key === 'net_income' ? 'font-semibold' : ''}`}>
              <th scope="row" className="px-5 py-2.5 text-left font-normal text-ink sm:px-6">{label}</th>
              <td className="px-5 py-2.5 text-right font-mono text-ink tabular-nums sm:px-6">{bridge[key] == null ? '—' : money(bridge[key])}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {bridge.non_operating_share_of_pretax != null && (
        <p className="border-t border-line px-5 py-3 text-xs text-ink-2 sm:px-6">
          Non-operating items are {formatPct(bridge.non_operating_share_of_pretax)} of income before taxes.
        </p>
      )}
      {bridge.items?.length > 0 && (
        <div className="border-t border-line px-5 py-3 sm:px-6">
          <p className="mb-2 text-[11px] font-semibold tracking-[0.08em] text-muted uppercase">Tagged non-operating and unusual items</p>
          <ul className="space-y-1.5">
            {bridge.items.filter((item) => item.value !== 0).slice(0, 8).map((item) => (
              <li key={item.key} className="flex items-baseline justify-between gap-4 text-sm">
                <span className="min-w-0 text-ink-2">
                  {item.label}
                  {item.source?.document_url && (
                    <a
                      href={item.source.element_id ? `${item.source.document_url}#${item.source.element_id}` : item.source.document_url}
                      target="_blank" rel="noreferrer" className="ml-1.5 inline-flex text-accent hover:text-accent-hover"
                      aria-label={`View ${item.label} in the filing`}
                    >
                      <ExternalLink size={11} />
                    </a>
                  )}
                </span>
                <span className="shrink-0 font-mono text-ink tabular-nums">{money(item.value)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  )
}

// Earnings against cash, year by year, from the stored statements.
function CashConversion({ table, currency }) {
  const get = (key) => table?.rows?.find((r) => r.key === key)
  const rows = [
    ['net_income', 'Net income', 'currency'],
    ['operating_cash_flow', 'Operating cash flow', 'currency'],
    ['cash_conversion', 'Operating cash flow / net income', 'ratio'],
    ['nonoperating_income', 'Non-operating income (expense)', 'currency'],
  ].map(([key, label, unit]) => ({ key, label, unit, row: get(key) })).filter((r) => r.row)
  if (!rows.length) return null
  return (
    <Card title="Earnings and cash, by year">
      <div className="relative overflow-x-auto">
        <table className="w-full min-w-[520px] border-collapse text-sm">
          <caption className="sr-only">Net income, operating cash flow and non-operating income by fiscal year</caption>
          <thead>
            <tr className="text-[11px] font-semibold tracking-[0.08em] text-muted uppercase">
              <th scope="col" className="px-5 py-2.5 text-left font-semibold sm:px-6">Item</th>
              {table.columns.map((c) => (
                <th key={`${c.fiscal_year}${c.fiscal_period}`} scope="col" className="px-3 py-2.5 text-right font-semibold last:pr-5 sm:last:pr-6">
                  {periodLabel(c.fiscal_year, c.fiscal_period)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map(({ key, label, unit, row }) => (
              <tr key={key} className="border-t border-line/60">
                <th scope="row" className="px-5 py-2.5 text-left font-normal text-ink sm:px-6">{label}</th>
                {row.values.map((cell, i) => (
                  <td key={i} className="px-3 py-2.5 text-right font-mono text-ink-2 tabular-nums last:pr-5 sm:last:pr-6">
                    {cell ? formatUnit(cell.v, unit, currency) : '—'}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

export default function EarningsTab({ research, request }) {
  const { insights, financials, earnings_quality: earnings } = research
  const currency = financials.currency ?? 'USD'
  const quality = insights?.earnings_quality
  return (
    <div>
      <SectionHeader eyebrow="Operating results versus everything else" title="Earnings quality" aside={<AiLabel insights={insights} />}>
        How much of net income comes from the business itself, and how much from investment gains, interest and one-time items, and
        whether cash from operations keeps up with reported earnings. The figures come from the filings&apos; tags; the explanation is
        neutral and does not judge whether a change is good or bad.
      </SectionHeader>
      <InsightsNotice insights={insights} request={request} />
      <div className="space-y-5">
        {quality?.summary && (
          <Card title="Summary">
            <p className="px-5 pt-4 text-sm leading-relaxed text-ink-2 sm:px-6">
              <FigureText text={quality.summary} spans={quality.figures} />
            </p>
            {quality.points?.length > 0 ? (
              <ul className="mt-2 divide-y divide-line border-t border-line">
                {quality.points.map((p, i) => <li key={i} className="px-5 py-4 sm:px-6"><SynthPoint item={p} /></li>)}
              </ul>
            ) : <div className="h-4" />}
          </Card>
        )}
        <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
          {(earnings?.bridges ?? []).map((b) => <Bridge key={b.label} bridge={b} currency={currency} />)}
        </div>
        <CashConversion table={financials.annual} currency={currency} />
        {quality && (
          <Card title="How the filings explain non-operating items">
            <QuotedList items={quality.explanations} empty="The filings read do not explain their non-operating items." />
          </Card>
        )}
      </div>
    </div>
  )
}
