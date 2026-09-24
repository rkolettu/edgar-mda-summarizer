import { dimIfUnverified, useVerifiedItems } from '../lib/verification'
import { Evidence, FigureText, UnverifiedToggle } from './Verification'

export default function AnalysisSection({ title, insights, sourceNote }) {
  const { visible, unverifiedCount, showUnverified, toggle } = useVerifiedItems(insights)

  return (
    <section className="editorial-card overflow-hidden rounded-2xl border border-line bg-panel">
      <header className="flex flex-wrap items-center gap-2.5 border-b border-line px-5 py-4 sm:px-6">
        <h3 className="text-base font-semibold tracking-[-0.025em] text-ink">{title}</h3>
        {sourceNote && <span className="hidden text-xs text-muted sm:inline">· {sourceNote}</span>}
        <span className="ml-auto font-mono text-xs text-muted">
          {visible.length} {visible.length === 1 ? 'insight' : 'insights'}
        </span>
      </header>

      {visible.length === 0 ? (
        <p className="px-5 py-4 text-sm text-muted sm:px-6">
          {unverifiedCount ? 'No insights could be verified against the filing.' : 'No insights returned for this section.'}
        </p>
      ) : (
        <ol className="divide-y divide-line">
          {visible.map((insight, i) => (
            <li key={i} className={`flex gap-4 px-5 py-5 sm:px-6 ${dimIfUnverified(insight)}`}>
              <span className="pt-0.5 font-mono text-xs text-muted tabular-nums">
                {String(i + 1).padStart(2, '0')}
              </span>
              <div className="min-w-0">
                <h4 className="text-[15px] leading-snug font-semibold text-ink">
                  <FigureText text={insight.headline} spans={insight.figures?.headline} />
                </h4>
                <p className="mt-1.5 text-sm leading-relaxed text-ink-2">
                  <FigureText text={insight.detail} spans={insight.figures?.detail} />
                </p>
                <Evidence item={insight} />
              </div>
            </li>
          ))}
        </ol>
      )}
      {unverifiedCount > 0 && (
        <div className="border-t border-line px-5 sm:px-6">
          <UnverifiedToggle count={unverifiedCount} shown={showUnverified} onToggle={toggle} />
        </div>
      )}
    </section>
  )
}
