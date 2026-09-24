import { CircleAlert, CircleCheck } from 'lucide-react'
import { STATUS } from '../lib/colors'

export function Evidence({ quote, verified, where = 'filing' }) {
  if (!quote) {
    return (
      <p className="mt-2 flex items-center gap-1.5 text-xs text-muted">
        <CircleAlert size={13} style={{ color: STATUS.warning }} aria-hidden />
        No source quote provided
      </p>
    )
  }
  const Icon = verified ? CircleCheck : CircleAlert
  return (
    <details className="group mt-2 text-xs">
      <summary className="flex w-fit cursor-pointer list-none items-center gap-1.5 text-muted select-none hover:text-ink-2">
        <Icon size={13} style={{ color: verified ? STATUS.good : STATUS.warning }} aria-hidden />
        {verified ? `Quote verified in ${where}` : `Quote not found verbatim in ${where}`}
        <span className="text-accent group-open:hidden">· Show source</span>
        <span className="hidden text-accent group-open:inline">· Hide source</span>
      </summary>
      <blockquote className="mt-2 border-l-2 border-line pl-3 leading-relaxed text-ink-2 italic">“{quote}”</blockquote>
    </details>
  )
}

export default function AnalysisSection({ title, insights, sourceNote }) {
  return (
    <section className="editorial-card overflow-hidden rounded-2xl border border-line bg-panel">
      <header className="flex flex-wrap items-center gap-2.5 border-b border-line px-5 py-4 sm:px-6">
        <h3 className="text-base font-semibold tracking-[-0.025em] text-ink">{title}</h3>
        {sourceNote && <span className="hidden text-xs text-muted sm:inline">· {sourceNote}</span>}
        <span className="ml-auto font-mono text-xs text-muted">
          {insights.length} {insights.length === 1 ? 'insight' : 'insights'}
        </span>
      </header>

      {insights.length === 0 ? (
        <p className="px-5 py-4 text-sm text-muted sm:px-6">No insights returned for this section.</p>
      ) : (
        <ol className="divide-y divide-line">
          {insights.map((insight, i) => (
            <li key={i} className="flex gap-4 px-5 py-5 sm:px-6">
              <span className="pt-0.5 font-mono text-xs text-muted tabular-nums">
                {String(i + 1).padStart(2, '0')}
              </span>
              <div className="min-w-0">
                <h4 className="text-[15px] leading-snug font-semibold text-ink">{insight.headline}</h4>
                <p className="mt-1.5 text-sm leading-relaxed text-ink-2">{insight.detail}</p>
                <Evidence quote={insight.evidence} verified={insight.verified} />
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}
