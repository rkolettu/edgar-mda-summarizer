import { useEffect, useState } from 'react'

function SkeletonLine({ className = '' }) {
  return <div className={`h-3 rounded bg-line/60 ${className}`} />
}

function SkeletonSection() {
  return (
    <div className="editorial-card rounded-2xl border border-line bg-panel p-6">
      <SkeletonLine className="mb-7 h-4 w-36" />
      {[0, 1, 2].map((i) => (
        <div key={i} className="mb-6 space-y-3 last:mb-0">
          <SkeletonLine className="h-3.5 w-2/3" />
          <SkeletonLine className="w-full opacity-60" />
          <SkeletonLine className="w-5/6 opacity-60" />
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
      <div className="mb-10 max-w-2xl border-b border-line pb-9">
        <p className="mb-4 text-[11px] font-semibold tracking-[0.14em] text-accent uppercase">Research in progress / {ticker}</p>
        <h1 className="text-3xl font-semibold tracking-[-0.05em] text-ink sm:text-4xl">Reading the filing.</h1>
        <p className="mt-3 text-sm leading-relaxed text-ink-2">
          A first-time analysis can take a few minutes. This uses my Gemini API key; if its usage limit is reached,
          please try again in about 3 hours.
        </p>
        <div className="loading-rule mt-6 h-1 w-full max-w-sm overflow-hidden rounded-full bg-line" aria-hidden="true" />
        <p className="mt-3 font-mono text-xs text-muted">{elapsed}s elapsed</p>
      </div>
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1.45fr)_minmax(0,1fr)]" aria-hidden="true">
        <div className="space-y-5"><SkeletonSection /><SkeletonSection /></div>
        <div className="space-y-5"><SkeletonSection /><SkeletonSection /></div>
      </div>
    </div>
  )
}
