export default function AnalysisSection({ title, icon: Icon, insights }) {
  return (
    <section className="rounded-lg border border-line bg-panel">
      <header className="flex items-center gap-2.5 border-b border-line px-5 py-3.5">
        <Icon size={17} className="text-accent" />
        <h2 className="text-sm font-semibold tracking-wide text-ink uppercase">{title}</h2>
        <span className="ml-auto font-mono text-xs text-muted">{insights.length} insights</span>
      </header>

      {insights.length === 0 ? (
        <p className="px-5 py-4 text-sm text-muted">No insights returned for this section.</p>
      ) : (
        <ol className="divide-y divide-line">
          {insights.map((insight, i) => (
            <li key={i} className="flex gap-4 px-5 py-4">
              <span className="pt-0.5 font-mono text-xs text-muted tabular-nums">
                {String(i + 1).padStart(2, '0')}
              </span>
              <div className="min-w-0">
                <h3 className="text-[15px] leading-snug font-semibold text-ink">{insight.headline}</h3>
                <p className="mt-1.5 text-sm leading-relaxed text-ink-2">{insight.detail}</p>
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}
