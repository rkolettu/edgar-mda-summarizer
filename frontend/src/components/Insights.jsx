import { CircleAlert, CircleCheck, Info, Loader2, Sparkles } from 'lucide-react'
import { STATUS } from '../lib/colors'
import { useVerifiedItems } from '../lib/verification'
import { Evidence, FigureText, UnverifiedToggle } from './Verification'

// Where an AI view stands: written, being written, unavailable, or not configured on this deployment.
export function InsightsNotice({ insights, request }) {
  if (insights?.status === 'ready') return null
  let text
  if (request?.status === 'loading') {
    text = 'Writing the AI analysis from the stored filings. It reads each filing once, which takes about a minute; later visits load it instantly.'
  } else if (request?.status === 'error') {
    text = request.error
  } else if (insights?.configured === false) {
    text = 'AI analysis is not configured on this deployment. Everything else on this page is built from the filings without it.'
  } else if (insights?.status === 'partial') {
    text = 'Part of the AI analysis is written; the summary will follow.'
  } else {
    return null
  }
  const Icon = request?.status === 'loading' ? Loader2 : Info
  return (
    <p className="mb-5 flex items-start gap-2 rounded-xl border border-line bg-panel px-5 py-4 text-sm text-ink-2" role="status">
      <Icon size={15} className={`mt-0.5 shrink-0 text-muted ${request?.status === 'loading' ? 'motion-safe:animate-spin' : ''}`} aria-hidden />
      {text}
    </p>
  )
}

export function AiLabel({ insights }) {
  if (!insights?.models?.length) return null
  return (
    <span className="inline-flex items-center gap-1 font-mono text-[11px] text-muted" title="Written by a model from the stored filings, then checked in code">
      <Sparkles size={11} aria-hidden /> AI · {insights.models.join(', ')}
    </span>
  )
}

export function SectionHeader({ eyebrow, title, aside, children }) {
  return (
    <div className="mb-6 border-b border-line pb-3">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="mb-1 text-[11px] font-semibold tracking-[0.14em] text-muted uppercase">{eyebrow}</p>
          <h2 className="text-2xl font-semibold tracking-[-0.04em] text-ink">{title}</h2>
        </div>
        {aside}
      </div>
      {children && <p className="mt-2 max-w-3xl text-sm leading-relaxed text-ink-2">{children}</p>}
    </div>
  )
}

export function Card({ title, aside, children, className = '' }) {
  return (
    <section className={`editorial-card overflow-hidden rounded-2xl border border-line bg-panel ${className}`}>
      {title && (
        <header className="flex flex-wrap items-center gap-2.5 border-b border-line px-5 py-4 sm:px-6">
          <h3 className="text-base font-semibold tracking-[-0.025em] text-ink">{title}</h3>
          {aside && <span className="ml-auto">{aside}</span>}
        </header>
      )}
      {children}
    </section>
  )
}

function sourceName(source) {
  return source ? `${source.fiscal_label ?? ''} ${source.form}`.trim() : 'filing'
}

// A statement extracted from one filing, with its verbatim quote checked against that filing.
export function QuotedItem({ item, badges }) {
  return (
    <>
      {badges && <div className="mb-1.5 flex flex-wrap items-center gap-1.5">{badges}</div>}
      <h4 className="text-[15px] leading-snug font-semibold text-ink">
        <FigureText text={item.headline} spans={item.figures?.headline} />
      </h4>
      {item.detail && (
        <p className="mt-1 text-sm leading-relaxed text-ink-2">
          <FigureText text={item.detail} spans={item.figures?.detail} />
        </p>
      )}
      <Evidence item={item} where={`the ${sourceName(item.source)}`} />
    </>
  )
}

// Quote-checked items, with unverified ones hidden until asked for.
export function QuotedList({ items, empty, badges }) {
  const { visible, unverifiedCount, showUnverified, toggle } = useVerifiedItems(items ?? [])
  if (!items?.length) return <p className="px-5 py-4 text-sm text-muted sm:px-6">{empty}</p>
  return (
    <>
      <ul className="divide-y divide-line">
        {visible.map((item, i) => (
          <li key={i} className={`px-5 py-4 sm:px-6 ${item.status === 'unverified' ? 'opacity-55' : ''}`}>
            <QuotedItem item={item} badges={badges?.(item)} />
          </li>
        ))}
      </ul>
      {unverifiedCount > 0 && (
        <div className="border-t border-line px-5 sm:px-6">
          <UnverifiedToggle count={unverifiedCount} shown={showUnverified} onToggle={toggle} />
        </div>
      )}
    </>
  )
}

const REF_KIND = { metric: 'Financials', change: 'Filing change', bridge: 'Earnings bridge', extraction: 'Filing' }

function refLabel(ref) {
  const where = ref.type === 'extraction' ? ref.form : REF_KIND[ref.type]
  return `${ref.label}${where ? ` (${where})` : ''}`
}

// How a synthesized statement is grounded: the stored facts it cites, and whether its figures were found in them.
export function Grounding({ item }) {
  const spans = [...(item.figures?.headline ?? []), ...(item.figures?.detail ?? [])]
  const untraced = spans.filter((s) => !s.verified).length
  const ok = untraced === 0
  const Icon = ok ? CircleCheck : CircleAlert
  return (
    <div className="mt-2 text-xs text-muted">
      <p className="flex items-start gap-1.5">
        <Icon size={13} className="mt-px shrink-0" style={{ color: ok ? STATUS.good : STATUS.warning }} aria-hidden />
        <span>
          {ok
            ? spans.length ? `${spans.length === 1 ? 'Figure' : `All ${spans.length} figures`} found in the stored data` : 'Based on stored data'
            : `${untraced} of ${spans.length} figures not found in the stored data`}
          {item.refs?.length ? ` · Based on ${item.refs.map(refLabel).join('; ')}` : ''}
        </span>
      </p>
    </div>
  )
}

export function SynthPoint({ item, badges }) {
  return (
    <>
      {badges && <div className="mb-1.5 flex flex-wrap items-center gap-1.5">{badges}</div>}
      <h4 className="text-[15px] leading-snug font-semibold text-ink">
        <FigureText text={item.headline} spans={item.figures?.headline} />
      </h4>
      <p className="mt-1 text-sm leading-relaxed text-ink-2">
        <FigureText text={item.detail} spans={item.figures?.detail} />
      </p>
      <Grounding item={item} />
    </>
  )
}

export function Badge({ children, tone = 'plain', icon: Icon }) {
  const tones = {
    plain: 'border-line bg-panel-2 text-ink',
    accent: 'border-accent/40 bg-accent/10 text-ink',
    quiet: 'border-line bg-panel text-ink-2',
  }
  return (
    <span className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[11px] font-medium ${tones[tone]}`}>
      {Icon && <Icon size={11} aria-hidden />}
      {children}
    </span>
  )
}
