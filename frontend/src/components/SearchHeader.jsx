import { FileText, LoaderCircle, Search } from 'lucide-react'

export default function SearchHeader({ ticker, onTickerChange, onSubmit, loading }) {
  return (
    <header className="sticky top-0 z-20 border-b border-line bg-page/90 backdrop-blur">
      <div className="mx-auto flex max-w-7xl flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center sm:gap-6 sm:px-6">
        <div className="flex items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-md bg-accent/15 text-accent">
            <FileText size={17} strokeWidth={2} />
          </div>
          <div className="leading-tight">
            <div className="text-sm font-semibold tracking-tight">Item 7 Extractor</div>
            <div className="text-[11px] text-muted">SEC 10-K MD&amp;A Intelligence</div>
          </div>
        </div>

        <form onSubmit={onSubmit} className="flex flex-1 gap-2 sm:ml-auto sm:max-w-md">
          <label className="relative flex-1">
            <span className="sr-only">Ticker symbol</span>
            <Search size={16} className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-muted" />
            <input
              value={ticker}
              onChange={(e) => onTickerChange(e.target.value.toUpperCase())}
              placeholder="Ticker, e.g. AAPL"
              maxLength={10}
              autoFocus
              spellCheck={false}
              className="h-10 w-full rounded-md border border-line bg-panel pr-3 pl-9 font-mono text-sm tracking-wider text-ink uppercase placeholder:font-sans placeholder:tracking-normal placeholder:normal-case placeholder:text-muted focus:border-accent focus:ring-2 focus:ring-accent/30 focus:outline-none"
            />
          </label>
          <button
            type="submit"
            disabled={loading || !ticker.trim()}
            className="flex h-10 items-center gap-2 rounded-md bg-accent px-4 text-sm font-semibold text-white transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:bg-panel-2 disabled:text-muted"
          >
            {loading && <LoaderCircle size={15} className="animate-spin" />}
            {loading ? 'Generating' : 'Generate'}
          </button>
        </form>
      </div>
    </header>
  )
}
