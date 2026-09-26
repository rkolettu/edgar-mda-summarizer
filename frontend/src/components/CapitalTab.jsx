import { ArrowDownRight, ArrowUpRight, CalendarClock, ChevronDown, ExternalLink, EyeOff, Plus } from 'lucide-react'
import { useState } from 'react'
import { formatSignedPct, formatUnit } from '../lib/format'

// Sections open on their largest items; the rest (individual notes, small charges) are one click away.
const VISIBLE_ITEMS = 6

const SECTION_NOTES = {
  customer_concentration: 'Customers are anonymized in filings and relabeled from one report to the next.',
  debt: 'Balances, facilities and individual notes as tagged in the debt note; issuance and repayment are cash flows for the period.',
}

function Badge({ icon: Icon, children, className }) {
  return (
    <span className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[11px] font-medium ${className}`}>
      <Icon size={11} aria-hidden />
      {children}
    </span>
  )
}

// Changes are shown in ink, not red or green: a rise in commitments or debt is not good or bad by itself.
// Above tenfold, a multiple reads better than a percentage ("126×" rather than "+12516.3%").
function Change({ value, basis }) {
  if (value === null || value === undefined) return <span className="text-muted">—</span>
  const Icon = value >= 0 ? ArrowUpRight : ArrowDownRight
  return (
    <span className="inline-flex items-center justify-end gap-0.5 text-ink">
      <Icon size={13} aria-hidden className="text-muted" />
      {value >= 9 ? `${(1 + value).toFixed(0)}×` : formatSignedPct(value)}
      <span className="sr-only"> {basis}</span>
    </span>
  )
}

function formatDate(iso) {
  return iso ? new Date(`${iso}T00:00:00Z`).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' }) : ''
}

function Amount({ point, unit, currency }) {
  if (!point) return <span className="text-muted">—</span>
  return (
    <span className="flex flex-col items-end">
      <span className="text-ink">{formatUnit(point.value, unit, currency)}</span>
      <span className="text-[11px] text-muted">{point.fiscal_label ?? formatDate(point.period_end)}</span>
    </span>
  )
}

function Source({ source }) {
  if (!source) return null
  const href = source.element_id ? `${source.document_url}#${source.element_id}` : source.document_url
  return (
    <details className="group mt-1.5 text-xs">
      <summary className="w-fit cursor-pointer list-none text-accent select-none hover:text-accent-hover">
        <span className="group-open:hidden">Show source</span>
        <span className="hidden group-open:inline">Hide source</span>
      </summary>
      <div className="mt-2 max-w-xl border-l-2 border-line pl-3 leading-relaxed text-ink-2">
        {source.heading && <p className="mb-1 text-[11px] text-muted">{source.heading}</p>}
        {source.text && <p className="italic">“{source.text}”</p>}
        <a href={href} target="_blank" rel="noreferrer" className="mt-1.5 inline-flex items-center gap-1 text-accent hover:text-accent-hover">
          View in filing <ExternalLink size={11} />
        </a>
      </div>
    </details>
  )
}

function ItemRow({ item }) {
  const flow = item.comparison === 'year_over_year'
  return (
    <tr className="border-t border-line/60 align-top">
      <th scope="row" className="px-5 py-3 text-left font-normal sm:px-6">
        <div className="text-ink">{item.label}</div>
        {item.reported_label && item.reported_label !== item.label && (
          <div className="text-xs text-muted">As reported: {item.reported_label}</div>
        )}
        {(item.is_new || item.subsequent_event || !item.in_latest_filing) && (
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {item.is_new && <Badge icon={Plus} className="border-accent/40 bg-accent/10 text-ink">New in latest filing</Badge>}
            {item.subsequent_event && <Badge icon={CalendarClock} className="border-line bg-panel-2 text-ink">Subsequent event</Badge>}
            {!item.in_latest_filing && <Badge icon={EyeOff} className="border-line bg-panel-2 text-ink-2">Not repeated in latest filing</Badge>}
          </div>
        )}
        <Source source={item.source} />
      </th>
      <td className="px-3 py-3 text-right font-mono tabular-nums"><Amount point={item.latest} unit={item.unit} currency={item.currency} /></td>
      <td className="px-3 py-3 text-right font-mono tabular-nums"><Amount point={item.prior} unit={item.unit} currency={item.currency} /></td>
      <td className="px-3 py-3 text-right font-mono tabular-nums"><Amount point={flow ? null : item.annual} unit={item.unit} currency={item.currency} /></td>
      <td className="px-5 py-3 text-right font-mono tabular-nums sm:px-6">
        <Change value={item.change_vs_prior} basis={flow ? 'versus the same period a year earlier' : 'versus the prior report'} />
      </td>
    </tr>
  )
}

function Section({ section }) {
  const [expanded, setExpanded] = useState(false)
  const hidden = section.items.length - VISIBLE_ITEMS
  const items = expanded || hidden <= 0 ? section.items : section.items.slice(0, VISIBLE_ITEMS)
  return (
    <section className="editorial-card overflow-hidden rounded-2xl border border-line bg-panel">
      <header className="flex flex-wrap items-center gap-2.5 border-b border-line px-5 py-4 sm:px-6">
        <h3 className="text-base font-semibold tracking-[-0.025em] text-ink">{section.label}</h3>
        <span className="ml-auto font-mono text-xs text-muted">
          {section.items.length} {section.items.length === 1 ? 'item' : 'items'}
          {section.more ? ` · ${section.more} smaller not shown` : ''}
        </span>
      </header>
      {SECTION_NOTES[section.key] && <p className="border-b border-line px-5 py-2.5 text-xs text-ink-2 sm:px-6">{SECTION_NOTES[section.key]}</p>}
      {/* relative: keeps screen-reader-only text (absolutely positioned) inside the scroll area on narrow screens */}
      <div className="relative overflow-x-auto">
        <table className="w-full min-w-[620px] border-collapse text-sm">
          <caption className="sr-only">{section.label}</caption>
          <thead>
            <tr className="text-[11px] font-semibold tracking-[0.08em] text-muted uppercase">
              <th scope="col" className="px-5 py-2.5 text-left font-semibold sm:px-6">Item</th>
              <th scope="col" className="px-3 py-2.5 text-right font-semibold">Latest</th>
              <th scope="col" className="px-3 py-2.5 text-right font-semibold">Prior</th>
              <th scope="col" className="px-3 py-2.5 text-right font-semibold">Last annual</th>
              <th scope="col" className="px-5 py-2.5 text-right font-semibold sm:px-6">Change</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => <ItemRow key={item.key} item={item} />)}
          </tbody>
        </table>
      </div>
      {hidden > 0 && (
        <button
          type="button"
          onClick={() => setExpanded(!expanded)}
          aria-expanded={expanded}
          className="flex w-full items-center justify-center gap-1.5 border-t border-line px-5 py-3 text-xs font-medium text-accent hover:bg-panel-2 hover:text-accent-hover"
        >
          <ChevronDown size={13} aria-hidden className={expanded ? 'rotate-180' : ''} />
          {expanded ? 'Show fewer' : `Show all ${section.items.length} items`}
        </button>
      )}
    </section>
  )
}

export default function CapitalTab({ research }) {
  const sections = research.capital?.sections ?? []
  const latest = research.filings?.find((f) => f.accession_number === research.latest_filing)
  return (
    <div>
      <div className="mb-6 border-b border-line pb-3">
        <p className="mb-1 text-[11px] font-semibold tracking-[0.14em] text-muted uppercase">Notes to the financial statements</p>
        <h2 className="text-2xl font-semibold tracking-[-0.04em] text-ink">Capital &amp; commitments</h2>
        <p className="mt-2 max-w-3xl text-sm leading-relaxed text-ink-2">
          Commitments, guarantees, financing and investments as tagged in the filings{latest ? `, through the ${latest.fiscal_label} ${latest.form}` : ''}.
          Balances compare with the previous report and the last annual report; amounts for a period compare with the same period a year
          earlier. Interim reports are condensed, so an item missing from the latest one is shown as of its last report.
        </p>
      </div>
      {sections.length === 0 ? (
        <p className="rounded-xl border border-line bg-panel px-5 py-5 text-sm text-muted">No commitments, guarantees or financing items are tagged in the stored filings.</p>
      ) : (
        <div className="space-y-5">
          {sections.map((section) => <Section key={section.key} section={section} />)}
        </div>
      )}
    </div>
  )
}
