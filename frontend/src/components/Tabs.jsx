import { useRef } from 'react'

// Accessible tab strip: arrow keys move between tabs, and only the selected tab is in the tab order.
export default function Tabs({ tabs, active, onChange, idPrefix = 'tab' }) {
  const refs = useRef({})

  function onKeyDown(event, index) {
    const step = { ArrowRight: 1, ArrowLeft: -1 }[event.key]
    const edge = { Home: 0, End: tabs.length - 1 }[event.key]
    if (step === undefined && edge === undefined) return
    event.preventDefault()
    const next = tabs[edge ?? (index + step + tabs.length) % tabs.length]
    onChange(next.key)
    refs.current[next.key]?.focus()
  }

  return (
    <div role="tablist" aria-label="Research views" className="-mx-5 mb-8 flex overflow-x-auto border-b border-line px-5 sm:mx-0 sm:px-0">
      {tabs.map((tab, index) => {
        const selected = tab.key === active
        return (
          <button
            key={tab.key}
            ref={(el) => (refs.current[tab.key] = el)}
            id={`${idPrefix}-${tab.key}`}
            role="tab"
            type="button"
            aria-selected={selected}
            aria-label={tab.label}
            aria-controls={`${idPrefix}-panel-${tab.key}`}
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(tab.key)}
            onKeyDown={(e) => onKeyDown(e, index)}
            className={`-mb-px shrink-0 border-b-2 px-3 py-3 text-sm font-medium whitespace-nowrap transition-colors first:pl-0 sm:px-4 sm:first:pl-4 ${
              selected ? 'border-accent text-ink' : 'border-transparent text-muted hover:text-ink-2'
            }`}
          >
            {tab.short ? (
              <>
                <span className="sm:hidden">{tab.short}</span>
                <span className="hidden sm:inline">{tab.label}</span>
              </>
            ) : (
              tab.label
            )}
          </button>
        )
      })}
    </div>
  )
}

export function TabPanel({ tabKey, active, idPrefix = 'tab', children }) {
  if (tabKey !== active) return null
  return (
    <div role="tabpanel" id={`${idPrefix}-panel-${tabKey}`} aria-labelledby={`${idPrefix}-${tabKey}`}>
      {children}
    </div>
  )
}
