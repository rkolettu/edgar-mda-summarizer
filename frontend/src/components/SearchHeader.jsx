import { ArrowUpRight, LoaderCircle, Search } from 'lucide-react'
import { useEffect, useId, useRef, useState } from 'react'
import { getJson } from '../lib/api'

const DEBOUNCE_MS = 150

function Highlight({ text, query }) {
  const q = query.trim()
  const i = q ? text.toLowerCase().indexOf(q.toLowerCase()) : -1
  if (i === -1) return text
  return (
    <>
      {text.slice(0, i)}
      <mark className="bg-transparent font-semibold text-ink">{text.slice(i, i + q.length)}</mark>
      {text.slice(i + q.length)}
    </>
  )
}

export default function SearchHeader({ query, onQueryChange, onSubmit, loading }) {
  const [suggestions, setSuggestions] = useState([])
  const [searched, setSearched] = useState('')
  const [open, setOpen] = useState(false)
  const [highlighted, setHighlighted] = useState(-1)
  const listId = useId()
  const skipNextSearch = useRef(false)

  useEffect(() => {
    if (skipNextSearch.current) {
      skipNextSearch.current = false
      return
    }
    const q = query.trim()
    if (!q) return
    const controller = new AbortController()
    const timer = setTimeout(() => {
      getJson('/api/search', { q, limit: 8 }, controller.signal)
        .then((results) => {
          setSuggestions(results)
          setSearched(q)
          setHighlighted(-1)
        })
        .catch(() => {})
    }, DEBOUNCE_MS)
    return () => {
      clearTimeout(timer)
      controller.abort()
    }
  }, [query])

  function choose(company) {
    skipNextSearch.current = true
    onQueryChange(company.ticker)
    setOpen(false)
    onSubmit(company.ticker)
  }

  function handleSubmit(e) {
    e.preventDefault()
    if (open && highlighted >= 0 && suggestions[highlighted]) {
      choose(suggestions[highlighted])
      return
    }
    setOpen(false)
    onSubmit(query)
  }

  function handleKeyDown(e) {
    if (e.key === 'ArrowDown' && suggestions.length) {
      e.preventDefault()
      setOpen(true)
      setHighlighted((h) => (h + 1) % suggestions.length)
    } else if (e.key === 'ArrowUp' && suggestions.length) {
      e.preventDefault()
      setOpen(true)
      setHighlighted((h) => (h <= 0 ? suggestions.length - 1 : h - 1))
    } else if (e.key === 'Escape') {
      setOpen(false)
    }
  }

  const q = query.trim()
  const showList = open && q.length > 0 && (suggestions.length > 0 || searched === q)

  return (
    <header className="relative z-20 border-b border-line bg-page/90">
      <div className="mx-auto flex max-w-6xl flex-col gap-5 px-5 py-5 sm:flex-row sm:items-center sm:gap-8 sm:px-8">
        <div className="flex shrink-0 items-center gap-3">
          <img src="/favicon.svg" width="36" height="36" alt="" className="h-9 w-9 shrink-0" />
          <div className="leading-tight">
            <div className="text-[15px] font-semibold tracking-[-0.04em] text-ink">EDGAR <span className="font-normal text-muted">/</span> Research</div>
            <div className="mt-0.5 text-[10px] font-medium tracking-[0.13em] text-muted uppercase">An annual filing workspace</div>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-1 gap-2 sm:ml-auto sm:max-w-xl">
          <div className="relative min-w-0 flex-1">
            <label htmlFor={`${listId}-input`} className="sr-only">
              Company or ticker
            </label>
            <Search size={16} className="pointer-events-none absolute top-1/2 left-3.5 -translate-y-1/2 text-muted" />
            <input
              id={`${listId}-input`}
              role="combobox"
              aria-expanded={showList}
              aria-controls={listId}
              aria-autocomplete="list"
              aria-activedescendant={highlighted >= 0 ? `${listId}-opt-${highlighted}` : undefined}
              value={query}
              onChange={(e) => {
                onQueryChange(e.target.value)
                setOpen(true)
              }}
              onFocus={() => setOpen(true)}
              onBlur={() => setOpen(false)}
              onKeyDown={handleKeyDown}
              placeholder="Company or ticker, e.g. Apple or AAPL"
              maxLength={100}
              autoFocus
              autoComplete="off"
              spellCheck={false}
              className="h-11 w-full rounded-xl border border-line bg-panel pr-3 pl-10 text-sm text-ink placeholder:text-muted focus:border-accent focus:ring-2 focus:ring-accent/15 focus:outline-none"
            />

            {showList && (
              <ul
                id={listId}
                role="listbox"
                className="absolute top-full right-0 left-0 z-30 mt-1.5 max-h-80 overflow-y-auto rounded-xl border border-line bg-panel py-1 shadow-xl shadow-black/10"
              >
                {suggestions.length === 0 ? (
                  <li className="px-3 py-2.5 text-sm text-muted">No SEC-registered company matches “{q}”</li>
                ) : (
                  suggestions.map((s, i) => (
                    <li
                      key={s.ticker}
                      id={`${listId}-opt-${i}`}
                      role="option"
                      aria-selected={i === highlighted}
                      onMouseDown={(e) => e.preventDefault()}
                      onMouseEnter={() => setHighlighted(i)}
                      onClick={() => choose(s)}
                      className={`flex cursor-pointer items-center gap-3 px-3 py-2 text-sm ${
                        i === highlighted ? 'bg-panel-2' : ''
                      }`}
                    >
                      <span className="w-16 shrink-0 font-mono text-xs text-ink">
                        <Highlight text={s.ticker} query={q} />
                      </span>
                      <span className="truncate text-ink-2">
                        <Highlight text={s.name} query={q} />
                      </span>
                    </li>
                  ))
                )}
              </ul>
            )}
          </div>
          <button
            type="submit"
            disabled={loading || !q}
            className="flex h-11 shrink-0 items-center gap-2 rounded-xl bg-ink px-4 text-sm font-semibold text-panel transition-colors hover:bg-accent disabled:cursor-not-allowed disabled:bg-line disabled:text-muted"
          >
            {loading && <LoaderCircle size={15} className="animate-spin" />}
            {loading ? 'Reading' : 'Analyze'}
            {!loading && <ArrowUpRight size={15} aria-hidden />}
          </button>
        </form>
      </div>
    </header>
  )
}
