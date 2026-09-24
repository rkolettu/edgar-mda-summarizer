export function ChartCard({ title, subtitle, footer, children }) {
  return (
    <section className="editorial-card overflow-hidden rounded-2xl border border-line bg-panel">
      <header className="flex items-center justify-between gap-3 border-b border-line px-5 py-4 sm:px-6">
        <h3 className="text-base font-semibold tracking-[-0.025em] text-ink">{title}</h3>
        {subtitle && <span className="text-xs text-muted">{subtitle}</span>}
      </header>
      <div className="p-5 sm:p-6">{children}</div>
      {footer && <footer className="border-t border-line px-5 py-3 text-[11px] leading-relaxed text-muted sm:px-6">{footer}</footer>}
    </section>
  )
}

export function ChartTooltip({ active, payload, formatValue }) {
  if (!active || !payload?.length) return null
  const { name, value } = payload[0].payload
  return (
    <div className="rounded-lg border border-line bg-panel px-3 py-2 text-xs shadow-lg shadow-black/10">
      <div className="font-medium text-ink">{name}</div>
      <div className="mt-0.5 font-mono text-ink-2 tabular-nums">
        {formatValue(value)}
      </div>
    </div>
  )
}

export function EmptyChart({ message }) {
  return (
    <div className="flex h-40 items-center justify-center rounded-md border border-dashed border-line text-sm text-muted">
      {message}
    </div>
  )
}
