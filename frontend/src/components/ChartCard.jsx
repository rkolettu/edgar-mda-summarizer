export function ChartCard({ title, subtitle, icon: Icon, children }) {
  return (
    <section className="rounded-lg border border-line bg-panel">
      <header className="flex items-center gap-2.5 border-b border-line px-5 py-3.5">
        <Icon size={17} className="text-accent" />
        <h2 className="text-sm font-semibold tracking-wide text-ink uppercase">{title}</h2>
        {subtitle && <span className="ml-auto text-xs text-muted">{subtitle}</span>}
      </header>
      <div className="p-5">{children}</div>
    </section>
  )
}

export function ChartTooltip({ active, payload, total, formatValue, formatShare }) {
  if (!active || !payload?.length) return null
  const { name, value } = payload[0].payload
  return (
    <div className="rounded-md border border-line bg-panel-2 px-3 py-2 text-xs shadow-xl shadow-black/40">
      <div className="font-medium text-ink">{name}</div>
      <div className="mt-0.5 font-mono text-ink-2 tabular-nums">
        {formatValue(value)}
        {total ? <span className="text-muted"> · {formatShare(value, total)}</span> : null}
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
