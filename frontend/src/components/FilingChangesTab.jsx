import { CalendarClock, ChevronDown, ExternalLink, Layers, Quote } from 'lucide-react'
import { useState } from 'react'
import { TypeTag } from './ChangesSection'
import { formatSignedPct, formatUnit } from '../lib/format'

const FILTERS = [
  { key: 'all', label: 'All' },
  { key: 'numbers', label: 'Numbers' },
  { key: 'language', label: 'Language' },
]

const TIERS = [
  { key: 'top', label: 'Most material' },
  { key: 'notable', label: 'Notable' },
  { key: 'background', label: 'Background' },
]

const FLAG_LABELS = {
  subsequent_event: 'Subsequent event',
  hypothetical_to_realized: 'Was hypothetical, now happened',
  new_financing: 'New financing',
}

function formatDate(iso) {
  return new Date(`${iso}T00:00:00Z`).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' })
}

// Period labels are fiscal ('Q2 FY2027') except for dates after a period end (subsequent events).
function period(label) {
  if (!label) return ''
  return /^\d{4}-\d{2}-\d{2}$/.test(label) ? `as of ${formatDate(label)}` : label
}

function value(amount, unit, currency) {
  return formatUnit(amount, unit === 'points' ? 'ratio' : unit, currency)
}

// Neutral wording: a rise in commitments or debt is not good or bad by itself. Above tenfold, a multiple reads better.
function changeText(item) {
  const { change, unit } = item
  if (unit === 'ratio' || unit === 'points') return change === null ? null : `${change > 0 ? '+' : ''}${(change * 100).toFixed(1)} pts`
  if (unit === 'days') return change === null ? null : `${change > 0 ? '+' : ''}${Math.round(change)} days`
  if (change === null) return item.base_value === 0 && item.value ? 'from zero' : null
  return change >= 9 ? `${(1 + change).toFixed(0)}×` : formatSignedPct(change)
}

function comparisonLabel(item) {
  if (item.comparison === 'year_over_year') return 'vs. a year earlier'
  if (item.base_filing) return `vs. ${item.base_filing.fiscal_label ?? ''} ${item.base_filing.form}`.replace('  ', ' ')
  return ''
}

function NumberLine({ item }) {
  if (item.values === 'growth') return <p className="mt-1.5 text-sm text-ink-2">{item.note}</p>
  const { unit, currency } = item
  if (item.change_type === 'removed') {
    return (
      <p className="mt-1.5 font-mono text-sm text-ink-2 tabular-nums">
        Was {value(item.base_value, unit, currency)} <span className="text-muted">({period(item.base_period_label)})</span>; not in this filing
      </p>
    )
  }
  const change = changeText(item)
  return (
    <div className="mt-1.5 flex flex-wrap items-baseline gap-x-2 gap-y-1 font-mono text-sm tabular-nums">
      {item.base_value !== null && item.base_value !== undefined && (
        <>
          <span className="text-ink-2">{value(item.base_value, unit, currency)}</span>
          <span className="text-[11px] text-muted">{period(item.base_period_label)}</span>
          <span aria-hidden className="text-muted">→</span>
          <span className="sr-only">to</span>
        </>
      )}
      <span className="font-semibold text-ink">{value(item.value, unit, currency)}</span>
      <span className="text-[11px] text-muted">{period(item.period_label)}</span>
      {change && <span className="rounded bg-panel-2 px-1.5 py-0.5 text-xs text-ink">{change}</span>}
      {item.annual_value !== null && item.annual_value !== undefined && (
        <span className="text-xs text-muted">· last annual {value(item.annual_value, unit, currency)}</span>
      )}
    </div>
  )
}

function Series({ item }) {
  const points = item.series ?? []
  if (points.length < 3 || item.unit !== 'currency') return null
  return (
    <p className="mt-1 text-xs text-muted">
      History: {points.map((p) => `${formatUnit(p.value, 'currency', item.currency)} (${period(p.label)})`).join(' → ')}
    </p>
  )
}

function Passage({ text, label }) {
  const long = text.length > 420
  const [open, setOpen] = useState(false)
  return (
    <div className="mt-2 max-w-3xl border-l-2 border-line pl-3">
      {label && <p className="mb-1 text-[11px] font-medium text-muted">{label}</p>}
      <p className="text-sm leading-relaxed text-ink-2">{long && !open ? `${text.slice(0, 400).replace(/\s+\S*$/, '')}…` : text}</p>
      {long && (
        <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} className="mt-1 text-xs text-accent hover:text-accent-hover">
          {open ? 'Show less' : 'Read the full passage'}
        </button>
      )}
    </div>
  )
}

function FilingLink({ item }) {
  const source = item.source
  const href = source ? (source.element_id ? `${source.document_url}#${source.element_id}` : source.document_url) : item.document_url
  if (!href) return null
  return (
    <a href={href} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs text-accent hover:text-accent-hover">
      View in filing <ExternalLink size={11} />
    </a>
  )
}

function Related({ items }) {
  if (!items?.length) return null
  return (
    <details className="group mt-2.5 text-xs">
      <summary className="flex w-fit cursor-pointer list-none items-center gap-1 text-accent select-none hover:text-accent-hover">
        <Layers size={12} aria-hidden />
        {items.length === 1 ? 'Also in this filing: 1 related item' : `Also in this filing: ${items.length} related items`}
        <ChevronDown size={12} aria-hidden className="group-open:rotate-180" />
      </summary>
      <ul className="mt-2 space-y-3">
        {items.map((r, i) => (
          <li key={i}>
            <p className="text-[11px] text-muted">
              {r.category_label} · {r.kind === 'narrative' ? 'wording' : r.label}
            </p>
            {r.kind === 'narrative' ? <Passage text={r.text} /> : <NumberLine item={r} />}
          </li>
        ))}
      </ul>
    </details>
  )
}

function ChangeItem({ item }) {
  const narrative = item.kind === 'narrative'
  const flags = (item.flags ?? []).filter((f) => FLAG_LABELS[f])
  return (
    <li className="px-5 py-5 sm:px-6">
      <div className="flex flex-wrap items-center gap-2">
        <TypeTag type={item.change_type} />
        <span className="text-[11px] font-semibold tracking-[0.08em] text-muted uppercase">{item.category_label}</span>
        {flags.map((f) => (
          <span key={f} className="inline-flex items-center gap-1 rounded border border-line bg-panel-2 px-1.5 py-0.5 text-[11px] font-medium text-ink">
            <CalendarClock size={11} aria-hidden />
            {FLAG_LABELS[f]}
          </span>
        ))}
        <span className="ml-auto text-[11px] text-muted">{comparisonLabel(item)}</span>
      </div>

      {narrative ? (
        <>
          <h4 className="mt-2 flex items-start gap-1.5 text-[15px] leading-snug font-semibold text-ink">
            <Quote size={14} aria-hidden className="mt-0.5 shrink-0 text-muted" />
            {item.change_type === 'removed' ? 'Wording no longer in the filing' : item.change_type === 'new' ? 'New wording' : 'Reworded'}
            {item.first_disclosed && <span className="font-normal text-muted"> · first disclosed in {item.first_disclosed}</span>}
          </h4>
          <Passage text={item.text} />
          {item.base_text && <Passage text={item.base_text} label={`Previously (${item.base_period_label ?? 'earlier filing'})`} />}
        </>
      ) : (
        <>
          <h4 className="mt-2 text-[15px] leading-snug font-semibold text-ink">{item.label}</h4>
          {item.reported_label && item.reported_label !== item.label && <p className="text-xs text-muted">As reported: {item.reported_label}</p>}
          {item.base_label && <p className="text-xs text-muted">Previously reported as: {item.base_label}</p>}
          <NumberLine item={item} />
          <Series item={item} />
          {item.note && item.values !== 'growth' && <p className="mt-1 text-xs text-ink-2">{item.note}</p>}
          {item.possibly_replaced_by && (
            <p className="mt-1 text-xs text-ink-2">Possibly renamed or split into: {item.possibly_replaced_by.join('; ')}</p>
          )}
        </>
      )}

      <div className="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-1.5">
        <p className="text-xs text-muted">
          <span className="font-mono text-ink-2">{item.score.toFixed(2)}</span>
          {item.reasons?.length ? ` · ${item.reasons.join(' · ')}` : ''}
        </p>
        <FilingLink item={item} />
      </div>
      <Related items={item.related} />
    </li>
  )
}

function Tier({ tier, items }) {
  if (!items.length) return null
  return (
    <section className="editorial-card overflow-hidden rounded-2xl border border-line bg-panel">
      <header className="flex flex-wrap items-center gap-2.5 border-b border-line px-5 py-4 sm:px-6">
        <h3 className="text-base font-semibold tracking-[-0.025em] text-ink">{tier.label}</h3>
        <span className="ml-auto font-mono text-xs text-muted">{items.length} {items.length === 1 ? 'item' : 'items'}</span>
      </header>
      <ol className="divide-y divide-line">
        {items.map((item, i) => <ChangeItem key={`${item.label}-${i}`} item={item} />)}
      </ol>
    </section>
  )
}

function Filter({ value: current, onChange }) {
  return (
    <div role="radiogroup" aria-label="Kind of change" className="inline-flex rounded-lg border border-line bg-panel p-0.5">
      {FILTERS.map((f) => (
        <button
          key={f.key}
          type="button"
          role="radio"
          aria-checked={current === f.key}
          onClick={() => onChange(f.key)}
          className={`rounded-md px-3 py-1.5 text-xs font-medium ${current === f.key ? 'bg-ink text-panel' : 'text-ink-2 hover:text-ink'}`}
        >
          {f.label}
        </button>
      ))}
    </div>
  )
}

function filingName(ref) {
  return ref ? `${ref.fiscal_label ?? ref.period_end} ${ref.form}` : null
}

export default function FilingChangesTab({ research }) {
  const [filter, setFilter] = useState('all')
  const [showBackground, setShowBackground] = useState(false)
  const changes = research.changes
  if (!changes?.filing) {
    return <p className="rounded-xl border border-line bg-panel px-5 py-5 text-sm text-muted">No filings are stored to compare yet.</p>
  }
  // Language includes tagged values that come with the filing's wording about them.
  const hasWording = (item) => item.kind === 'narrative' || item.related?.some((r) => r.kind === 'narrative')
  const matches = (item) => filter === 'all' || (filter === 'language' ? hasWording(item) : item.kind !== 'narrative')
  const items = changes.items.filter(matches)
  const byTier = Object.fromEntries(TIERS.map((t) => [t.key, items.filter((i) => i.tier === t.key)]))
  const background = byTier.background.length
  const bases = [
    changes.previous && `the ${filingName(changes.previous)} (the previous report)`,
    changes.annual && changes.annual.accession_number !== changes.previous?.accession_number && `the ${filingName(changes.annual)} (the last annual report)`,
  ].filter(Boolean)

  return (
    <div>
      <div className="mb-6 border-b border-line pb-3">
        <p className="mb-1 text-[11px] font-semibold tracking-[0.14em] text-muted uppercase">Latest filing vs. earlier reports</p>
        <h2 className="text-2xl font-semibold tracking-[-0.04em] text-ink">Filing changes</h2>
        <p className="mt-2 max-w-3xl text-sm leading-relaxed text-ink-2">
          {`What the ${filingName(changes.filing)} adds, changes or drops compared with ${bases.length ? bases.join(' and ') : 'earlier filings'}; `}
          amounts for a period compare with the same period a year earlier. Items are ranked by a score computed from the filings
          without AI: the amount relative to the company&apos;s revenue, operating income and assets, how much it moved, the kind of
          disclosure, flagged wording, and whether it is new. Tagged values and the wording about the same amount are shown together.
        </p>
      </div>

      <div className="mb-5 flex flex-wrap items-center gap-3">
        <Filter value={filter} onChange={setFilter} />
        <p className="text-xs text-muted">
          {['new', 'changed', 'removed'].filter((k) => changes.counts?.[k]).map((k) => `${changes.counts[k]} ${k}`).join(' · ')}
        </p>
      </div>

      {items.length === 0 ? (
        <p className="rounded-xl border border-line bg-panel px-5 py-5 text-sm text-muted">No changes of this kind in the latest filing.</p>
      ) : (
        <div className="space-y-5">
          <Tier tier={TIERS[0]} items={byTier.top} />
          <Tier tier={TIERS[1]} items={byTier.notable} />
          {showBackground && <Tier tier={TIERS[2]} items={byTier.background} />}
          {background > 0 && (
            <button
              type="button"
              onClick={() => setShowBackground(!showBackground)}
              aria-expanded={showBackground}
              className="flex w-full items-center justify-center gap-1.5 rounded-xl border border-line bg-panel px-5 py-3 text-xs font-medium text-accent hover:bg-panel-2 hover:text-accent-hover"
            >
              <ChevronDown size={13} aria-hidden className={showBackground ? 'rotate-180' : ''} />
              {showBackground ? 'Hide background items' : `Show ${background} background ${background === 1 ? 'item' : 'items'}`}
            </button>
          )}
          {changes.hidden > 0 && showBackground && (
            <p className="text-center text-xs text-muted">{changes.hidden} lower-ranked items are not shown.</p>
          )}
        </div>
      )}
      <p className="mt-6 text-xs text-muted">
        Scores run from 0 to 1; 0.70 and above is most material and 0.45 and above notable. They rank changes for review and do not
        judge whether a change is good or bad.
      </p>
    </div>
  )
}
