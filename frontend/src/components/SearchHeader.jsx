import CompanySearch from './CompanySearch'

export default function SearchHeader({ query, onQueryChange, onSubmit, loading, onHome, landing }) {
  return (
    <header className="relative z-20 border-b border-line bg-panel">
      <div className="mx-auto flex max-w-6xl flex-col gap-5 px-5 py-5 sm:flex-row sm:items-center sm:gap-8 sm:px-8">
        <a href="/" onClick={(e) => { e.preventDefault(); onHome?.() }} aria-label="EDGAR Research, home"
          className="flex shrink-0 items-center gap-3 rounded-lg hover:opacity-80">
          <img src="/favicon.svg" width="36" height="36" alt="" className="h-9 w-9 shrink-0" />
          <div className="leading-tight">
            <div className="text-[15px] font-semibold tracking-[-0.04em] text-ink">EDGAR <span className="font-normal text-gold">/</span> Research</div>
            <div className="mt-0.5 text-[10px] font-medium tracking-[0.13em] text-muted uppercase">An annual filing workspace</div>
          </div>
        </a>
        {!landing && <CompanySearch query={query} onQueryChange={onQueryChange} onSubmit={onSubmit} loading={loading} />}
      </div>
    </header>
  )
}
