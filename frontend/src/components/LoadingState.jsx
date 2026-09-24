import { useEffect, useState } from 'react'

function SkeletonLine({ className = '' }) {
  return <div className={`h-3 rounded bg-panel-2 ${className}`} />
}

function SkeletonSection() {
  return (
    <div className="rounded-lg border border-line bg-panel p-5">
      <SkeletonLine className="mb-5 h-4 w-40" />
      {[0, 1, 2].map((i) => (
        <div key={i} className="mb-5 space-y-2.5 last:mb-0">
          <SkeletonLine className="h-3.5 w-2/3 bg-line" />
          <SkeletonLine className="w-full" />
          <SkeletonLine className="w-11/12" />
          <SkeletonLine className="w-4/6" />
        </div>
      ))}
    </div>
  )
}

export default function LoadingState({ ticker }) {
  const [elapsed, setElapsed] = useState(0)
  useEffect(() => {
    const id = setInterval(() => setElapsed((e) => e + 1), 1000)
    return () => clearInterval(id)
  }, [])

  return (
    <div role="status" aria-live="polite">
      <div className="mb-6 flex flex-col items-center gap-3 rounded-lg border border-accent/30 bg-accent/5 px-4 py-6 text-center">
        <div className="relative flex h-3 w-3">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-accent opacity-60" />
          <span className="relative inline-flex h-3 w-3 rounded-full bg-accent" />
        </div>
        <p className="text-sm font-medium text-ink">
          Parsing SEC EDGAR Filings &amp; Generating Institutional Insights...
        </p>
        <p className="font-mono text-xs text-muted">
          {ticker} · {elapsed}s elapsed · first run typically 20–40s, repeats are instant
        </p>
      </div>

      <div className="grid animate-pulse grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1.45fr)_minmax(0,1fr)]">
        <div className="space-y-6">
          <SkeletonSection />
          <SkeletonSection />
        </div>
        <div className="space-y-6">
          <div className="rounded-lg border border-line bg-panel p-5">
            <SkeletonLine className="mb-6 h-4 w-36" />
            <div className="mx-auto h-48 w-48 rounded-full border-[22px] border-panel-2" />
          </div>
          <div className="rounded-lg border border-line bg-panel p-5">
            <SkeletonLine className="mb-6 h-4 w-36" />
            {[90, 70, 45, 30].map((w) => (
              <div key={w} className="mb-3 h-5 rounded bg-panel-2" style={{ width: `${w}%` }} />
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
