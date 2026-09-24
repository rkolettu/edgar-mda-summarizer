import { ArrowLeftRight, ExternalLink, Minus, Plus } from 'lucide-react'
import { fiscalYearLabel } from '../lib/format'
import { Evidence } from './AnalysisSection'

const TYPES = {
  new: { label: 'New', icon: Plus, className: 'border-accent/40 bg-accent/10 text-ink' },
  removed: { label: 'Removed', icon: Minus, className: 'border-line bg-panel-2 text-ink-2' },
  changed: { label: 'Changed', icon: ArrowLeftRight, className: 'border-line bg-panel-2 text-ink' },
}

function TypeTag({ type }) {
  const { label, icon: Icon, className } = TYPES[type] ?? TYPES.changed
  return (
    <span className={`inline-flex shrink-0 items-center gap-1 rounded border px-1.5 py-0.5 text-[11px] font-medium ${className}`}>
      <Icon size={11} aria-hidden />
      {label}
    </span>
  )
}

export default function ChangesSection({ changes }) {
  const prior = changes.prior_filing
  return (
    <section className="editorial-card overflow-hidden rounded-2xl border border-line bg-panel">
      <header className="flex flex-wrap items-center gap-2.5 border-b border-line px-5 py-4 sm:px-6">
        <h3 className="text-base font-semibold tracking-[-0.025em] text-ink">
          What changed vs. {fiscalYearLabel(prior.report_date)} 10-K
        </h3>
        <a
          href={prior.document_url}
          target="_blank"
          rel="noreferrer"
          className="ml-auto flex items-center gap-1 text-xs text-accent hover:text-accent-hover"
        >
          Prior filing <ExternalLink size={11} />
        </a>
      </header>

      {changes.items.length === 0 ? (
        <p className="px-5 py-4 text-sm text-muted sm:px-6">No material changes identified.</p>
      ) : (
        <ol className="divide-y divide-line">
          {changes.items.map((item, i) => (
            <li key={i} className="px-5 py-5 sm:px-6">
              <div className="flex flex-wrap items-center gap-2">
                <TypeTag type={item.change_type} />
                <h3 className="text-[15px] leading-snug font-semibold text-ink">{item.headline}</h3>
              </div>
              <p className="mt-1.5 text-sm leading-relaxed text-ink-2">{item.detail}</p>
              <Evidence
                quote={item.evidence}
                verified={item.verified}
                where={item.change_type === 'removed' ? 'prior filing' : 'latest filing'}
              />
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}
