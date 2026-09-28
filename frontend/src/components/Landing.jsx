import { ArrowRight, ArrowUpRight, Check, Info, Search } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import CandleField from './CandleField'

const HEADLINE_WORDS = ['numbers', 'headlines', 'footnotes', 'guidance']

// The showcase companies (backend/research/watchlist.txt) load instantly; the rest are parsed on the first visit.
const COMPANIES = [
  { ticker: 'NVDA', name: 'NVIDIA' },
  { ticker: 'AAPL', name: 'Apple' },
  { ticker: 'MSFT', name: 'Microsoft' },
  { ticker: 'AMZN', name: 'Amazon' },
  { ticker: 'JPM', name: 'JPMorgan Chase' },
  { ticker: 'TSM', name: 'TSMC' },
  { ticker: 'ASML', name: 'ASML' },
  { ticker: 'SU', name: 'Suncor Energy' },
  { ticker: 'TD', name: 'Toronto-Dominion Bank' },
  { ticker: 'HSBC', name: 'HSBC' },
  { ticker: 'SHEL', name: 'Shell' },
  { ticker: 'UBS', name: 'UBS' },
]

const STEPS = [
  { key: 'search', label: 'Search', title: 'Pick any SEC registrant', body: 'Type a ticker or a name. Every company that files annual reports on EDGAR is searchable.' },
  { key: 'parse', label: 'Parse', title: 'Filings become structured facts', body: 'Code reads the latest annual report and recent quarters once and stores them. No model is involved in the numbers.' },
  { key: 'compare', label: 'Compare', title: 'See what changed', body: 'The latest filing is compared with last year’s: what it adds, rewrites or drops, ranked by materiality.' },
  { key: 'verify', label: 'Verify', title: 'The analysis is checked', body: 'AI writes the memo from the stored facts. Each insight quotes the filing, and the quote and figures are matched back to it.' },
]
const STEP_MS = 5000

const BTN_PRIMARY = 'group inline-flex h-12 items-center gap-2 rounded-lg bg-ink px-5 text-[15px] font-semibold text-panel transition-colors hover:bg-accent'
const BTN_SECONDARY = 'group inline-flex h-12 items-center gap-2 rounded-lg border border-line bg-panel px-5 text-[15px] font-semibold text-ink transition-colors hover:border-ink'
const LABEL = 'text-[11px] font-semibold tracking-[0.14em] uppercase'
const CARD = 'rounded-2xl border border-line bg-panel'

function usePrefersReducedMotion() {
  const [reduced, setReduced] = useState(() => window.matchMedia('(prefers-reduced-motion: reduce)').matches)
  useEffect(() => {
    const query = window.matchMedia('(prefers-reduced-motion: reduce)')
    const onChange = () => setReduced(query.matches)
    query.addEventListener('change', onChange)
    return () => query.removeEventListener('change', onChange)
  }, [])
  return reduced
}

function useInView(margin = '0px 0px -10% 0px') {
  const ref = useRef(null)
  const [inView, setInView] = useState(false)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) {
        setInView(true)
        observer.disconnect()
      }
    }, { rootMargin: margin })
    observer.observe(el)
    return () => observer.disconnect()
  }, [margin])
  return [ref, inView]
}

// Fades its children up the first time they scroll into view; `is-shown` also starts any illustration inside.
function Reveal({ as: Tag = 'div', delay = 0, className = '', children, ...rest }) {
  const [ref, shown] = useInView()
  return (
    <Tag ref={ref} className={`reveal ${shown ? 'is-shown' : ''} ${className}`} style={{ transitionDelay: `${delay}ms` }} {...rest}>
      {children}
    </Tag>
  )
}

function SectionLabel({ children }) {
  return <p className={`mb-4 ${LABEL} text-muted`}>{children}</p>
}

function RotatingWord() {
  const reduced = usePrefersReducedMotion()
  const [index, setIndex] = useState(0)
  useEffect(() => {
    if (reduced) return
    const id = setInterval(() => setIndex((i) => (i + 1) % HEADLINE_WORDS.length), 2600)
    return () => clearInterval(id)
  }, [reduced])
  const word = HEADLINE_WORDS[index]
  return (
    <span className="whitespace-nowrap">
      the{' '}
      <span className="relative inline-block">
        <span key={word} className="word-in inline-block">{word}</span>
        <span aria-hidden key={`u-${word}`} className="underline-in absolute inset-x-0 bottom-[0.02em] h-[0.1em] rounded-full bg-accent/25" />
      </span>
      .
    </span>
  )
}

function Hero({ onPick, onSearch }) {
  return (
    <div className="relative overflow-hidden">
      <CandleField className="field-fade absolute top-0 right-[-35%] h-full w-[125%] opacity-35 sm:right-[-15%] sm:w-[85%] sm:opacity-70 lg:right-[-6%] lg:w-[62%] lg:opacity-100" />
      <section className="relative mx-auto flex max-w-6xl items-center px-5 pt-14 pb-16 sm:px-8 sm:pt-20 lg:min-h-[620px] lg:pt-20 lg:pb-20">
        <div className="max-w-[40rem]">
          <Reveal as="p" className={`mb-6 ${LABEL} text-accent`}>SEC EDGAR / Filing research</Reveal>
          <Reveal as="h1" delay={60} className="text-[clamp(3rem,6vw,5.5rem)] leading-[0.95] font-[650] tracking-[-0.06em] text-ink">
            <span aria-hidden>
              Read beyond
              <br />
              <RotatingWord />
            </span>
            <span className="sr-only">Read beyond the numbers.</span>
          </Reveal>
          <Reveal as="p" delay={120} className="mt-7 max-w-lg text-lg leading-relaxed text-ink-2 sm:text-xl">
            Start with a company. Follow the financials, see what management says changed, and trace each insight back to the filing.
          </Reveal>
          <Reveal delay={180} className="mt-9 flex flex-wrap gap-3">
            <button type="button" onClick={onSearch} className={BTN_PRIMARY}>
              Search a company <ArrowRight size={16} className="transition-transform group-hover:translate-x-0.5" aria-hidden />
            </button>
            <button type="button" onClick={() => onPick('NVDA')} className={BTN_SECONDARY}>
              Try NVIDIA <ArrowUpRight size={15} className="text-muted transition-colors group-hover:text-ink" aria-hidden />
            </button>
          </Reveal>
          <Reveal as="p" delay={240} className={`mt-8 ${LABEL} tracking-[0.12em] text-muted`}>
            Free <span className="mx-2 text-line">/</span> No account <span className="mx-2 text-line">/</span> Source: SEC EDGAR
          </Reveal>
        </div>
      </section>
    </div>
  )
}

const LIFTED = 'shadow-[0_24px_60px_-20px_rgba(36,31,24,0.25)]'

// The product cards: shown under the hero, and again in the process step each one illustrates.
function MdnaCard({ className = '', style }) {
  return (
    <div className={`${CARD} p-5 ${className}`} style={style}>
      <div className="mb-4 flex items-center justify-between">
        <span className={`${LABEL} text-muted`}>Item 7 · MD&amp;A</span>
        <span className="rounded-md border border-line px-1.5 py-0.5 font-mono text-[10px] text-ink-2">10-K</span>
      </div>
      <div className="space-y-2.5">
        <Line w="92%" />
        <Line w="84%" />
        <div className="relative">
          <span className="sweep absolute -inset-x-1.5 -inset-y-1 rounded bg-accent/12" />
          <Line w="96%" dark />
        </div>
        <div className="relative">
          <span className="sweep absolute -inset-x-1.5 -inset-y-1 rounded bg-accent/12" style={{ animationDelay: '0.25s' }} />
          <Line w="61%" dark />
        </div>
        <Line w="88%" />
        <Line w="72%" />
      </div>
      <div className="badge-pop mt-4 inline-flex items-center gap-1.5 rounded-md bg-[#287252]/10 px-2 py-1 text-[11px] font-semibold text-[#287252]">
        <Check size={12} strokeWidth={3} /> Quote found in filing
      </div>
    </div>
  )
}

function TrendCard({ className = '', style }) {
  return (
    <div className={`${CARD} p-5 ${className}`} style={style}>
      <div className="mb-3 flex items-center justify-between">
        <span className={`${LABEL} text-muted`}>Five-year trend</span>
        <span className="flex gap-2.5 text-[10px] text-ink-2">
          <span className="flex items-center gap-1"><span className="h-1.5 w-1.5 rounded-full bg-[#355e99]" />Revenue</span>
          <span className="flex items-center gap-1"><span className="h-1.5 w-1.5 rounded-full bg-[#c8702a]" />FCF</span>
        </span>
      </div>
      <TrendSvg />
    </div>
  )
}

function ChangesCard({ className = '', style }) {
  return (
    <div className={`${CARD} p-4 ${className}`} style={style}>
      <span className={`${LABEL} text-muted`}>Filing changes</span>
      <ul className="mt-3 space-y-2 text-[12px] text-ink-2">
        <ChangeRow sign="+" color="#287252" label="New risk factor" w="85%" />
        <ChangeRow sign="~" color="#946819" label="Guidance reworded" w="60%" />
        <ChangeRow sign="−" color="#a43e39" label="Segment dropped" w="40%" />
      </ul>
    </div>
  )
}

const SHOWCASE = [
  { card: MdnaCard, title: 'Management discussion', body: 'Every insight quotes the filing, and the quote is matched against it.' },
  { card: TrendCard, title: 'Five-year trends', body: 'Revenue, margins and cash flow from the filing’s own XBRL tags.' },
  { card: ChangesCard, title: 'Filing changes', body: 'What the latest report adds, rewrites or drops versus last year’s.' },
]

// The product cards side by side under the hero, each with a caption.
function Showcase() {
  return (
    <section aria-labelledby="showcase-heading" className="mx-auto max-w-6xl px-5 pb-16 sm:px-8 sm:pb-24">
      <p id="showcase-heading" className={`mb-5 ${LABEL} text-muted`}>Inside a company page</p>
      <div className="grid gap-4 md:grid-cols-3">
        {SHOWCASE.map(({ card: Card, title, body }, i) => (
          <Reveal key={title} delay={i * 90} className="group">
            <div className="h-64 overflow-hidden rounded-2xl border border-line bg-panel-2 p-5 transition-colors duration-500 group-hover:bg-panel">
              <Card className={`transition-transform duration-500 group-hover:-translate-y-1 ${LIFTED}`} />
            </div>
            <h3 className="mt-4 text-lg font-[620] tracking-[-0.03em] text-ink">{title}</h3>
            <p className="mt-1 text-[15px] leading-relaxed text-ink-2">{body}</p>
          </Reveal>
        ))}
      </div>
    </section>
  )
}

function Line({ w, dark = false }) {
  return <div className={`relative h-2 rounded-full ${dark ? 'bg-ink/70' : 'bg-line/80'}`} style={{ width: w }} />
}

function ChangeRow({ sign, color, label, w }) {
  return (
    <li className="grid grid-cols-[0.9rem_minmax(0,1fr)] items-center gap-x-1.5">
      <span className="font-mono font-semibold" style={{ color }}>{sign}</span>
      <span className="truncate">{label}</span>
      <span />
      <span className="mt-1 h-1 rounded-full bg-line/70">
        <span className="grow-x block h-1 rounded-full" style={{ width: w, background: color, opacity: 0.55 }} />
      </span>
    </li>
  )
}

// Rising revenue bars with free cash flow drawn over them. Illustrative shape only, no figures.
function TrendSvg({ className = 'h-32 w-full' }) {
  const bars = [38, 47, 55, 70, 88]
  const fcf = [22, 30, 27, 42, 58]
  const x = (i) => 14 + i * 38
  const points = fcf.map((v, i) => `${x(i) + 9},${100 - v}`).join(' ')
  return (
    <svg viewBox="0 0 190 104" className={className} preserveAspectRatio="none">
      {[25, 50, 75].map((y) => <line key={y} x1="0" x2="190" y1={y} y2={y} stroke="#ebe7df" strokeWidth="1" />)}
      {bars.map((h, i) => (
        <rect key={i} x={x(i)} y={100 - h} width="18" height={h} rx="2" fill="#355e99" opacity={0.35 + i * 0.13} className="grow-y" style={{ animationDelay: `${150 + i * 90}ms` }} />
      ))}
      <polyline points={points} fill="none" stroke="#c8702a" strokeWidth="2.25" strokeLinejoin="round" strokeLinecap="round" pathLength="1" className="draw" />
      {fcf.map((v, i) => <circle key={i} cx={x(i) + 9} cy={100 - v} r="2.6" fill="#fffefa" stroke="#c8702a" strokeWidth="1.75" className="dot-in" style={{ animationDelay: `${900 + i * 80}ms` }} />)}
      <line x1="0" x2="190" y1="100.5" y2="100.5" stroke="#d2cdc4" strokeWidth="1" />
    </svg>
  )
}

// A slim strip of companies to try, right under the site header.
function CompanyMarquee({ onPick }) {
  const row = (hidden) => (
    <ul className="flex shrink-0 gap-2 pr-2" aria-hidden={hidden || undefined}>
      {COMPANIES.map((c) => (
        <li key={c.ticker} className="shrink-0">
          <button
            type="button"
            tabIndex={hidden ? -1 : undefined}
            onClick={() => onPick(c.ticker)}
            className="group flex items-center gap-2 rounded-lg border border-line bg-panel px-3 py-1.5 transition-colors hover:border-ink"
          >
            <span className="font-mono text-[11px] font-medium text-ink">{c.ticker}</span>
            <span className="text-[13px] text-ink-2">{c.name}</span>
            <ArrowUpRight size={12} className="text-muted transition-colors group-hover:text-ink" aria-hidden />
          </button>
        </li>
      ))}
    </ul>
  )
  return (
    <section aria-label="Try a company" className="border-b border-line/70">
      <div className="mx-auto flex max-w-6xl items-center gap-4 px-5 py-3 sm:gap-6 sm:px-8">
        <p className={`shrink-0 ${LABEL} text-muted`} title="Showcase companies load instantly. Others take about a minute the first time.">
          Try a company
        </p>
        <div className="marquee-mask marquee-pause min-w-0 flex-1">
          <div className="marquee flex w-max">
            {row(false)}
            {row(true)}
          </div>
        </div>
      </div>
    </section>
  )
}

function Process() {
  const reduced = usePrefersReducedMotion()
  const [ref, inView] = useInView()
  const [active, setActive] = useState(0)
  const [cycle, setCycle] = useState(0)  // restarts the timer after a click

  useEffect(() => {
    if (reduced || !inView) return
    const id = setTimeout(() => setActive((a) => (a + 1) % STEPS.length), STEP_MS)
    return () => clearTimeout(id)
  }, [active, cycle, reduced, inView])

  const step = STEPS[active]
  return (
    <section className="border-t border-line">
      <div className="mx-auto grid max-w-6xl gap-10 px-5 py-16 sm:px-8 sm:py-24 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)] lg:gap-16">
        <Reveal>
          <SectionLabel>Process</SectionLabel>
          <h2 className="text-[clamp(2.4rem,5vw,3.6rem)] leading-[1.02] font-[620] tracking-[-0.045em] text-ink">How a company page comes together</h2>
          <p className="mt-5 max-w-sm text-lg leading-relaxed text-ink-2">
            The numbers come from code, the writing from AI, and every claim is checked before you see it.
          </p>
        </Reveal>

        <Reveal delay={100} className={`${CARD} editorial-card overflow-hidden`}>
          <div ref={ref} className="grid grid-cols-4 border-b border-line" role="tablist" aria-label="Process steps">
            {STEPS.map((s, i) => (
              <button
                key={s.key}
                type="button"
                role="tab"
                aria-selected={i === active}
                onClick={() => {
                  setActive(i)
                  setCycle((c) => c + 1)
                }}
                className={`relative px-3 py-4 text-left transition-colors sm:px-6 ${i ? 'border-l border-line' : ''} ${i === active ? 'bg-panel' : 'bg-panel-2 hover:bg-panel'}`}
              >
                <span className="font-mono text-[11px] text-muted">{String(i + 1).padStart(2, '0')}</span>
                <span className={`mt-0.5 block text-sm font-semibold ${i === active ? 'text-ink' : 'text-ink-2'}`}>{s.label}</span>
                <span className="absolute inset-x-0 bottom-0 h-0.5 bg-transparent">
                  {i === active && (
                    <span
                      key={`${active}-${cycle}-${inView}`}
                      className={`block h-full bg-accent ${reduced || !inView ? 'w-full' : 'step-progress'}`}
                      style={{ animationDuration: `${STEP_MS}ms` }}
                    />
                  )}
                  {i < active && <span className="block h-full w-full bg-accent/30" />}
                </span>
              </button>
            ))}
          </div>
          <div className="p-6 sm:p-8" role="tabpanel" aria-live="polite">
            <div key={active} className="step-in">
              <h3 className="text-xl font-[620] tracking-[-0.035em] text-ink sm:text-2xl">{step.title}</h3>
              <p className="mt-2 max-w-lg text-[15px] leading-relaxed text-ink-2">{step.body}</p>
              <div className="mt-7 flex min-h-[16rem] items-center justify-center rounded-xl border border-line bg-panel-2 p-5" aria-hidden>
                {step.key === 'search' && <SearchPreview />}
                {step.key === 'parse' && <TrendCard className={`w-full max-w-sm ${LIFTED}`} />}
                {step.key === 'compare' && <ChangesCard className={`w-full max-w-xs ${LIFTED}`} />}
                {step.key === 'verify' && <MdnaCard className={`w-full max-w-sm ${LIFTED}`} />}
              </div>
            </div>
          </div>
        </Reveal>
      </div>
    </section>
  )
}

function SearchPreview() {
  return (
    <div className="w-full max-w-sm">
      <div className="flex h-10 items-center gap-2.5 rounded-lg border border-accent bg-panel px-3 ring-2 ring-accent/15">
        <Search size={14} className="text-muted" />
        <span className="typing font-mono text-[13px] text-ink">nvidia</span>
        <span className="caret h-4 w-px bg-ink" />
      </div>
      <ul className="mt-1.5 overflow-hidden rounded-lg border border-line bg-panel py-1 text-[13px] shadow-lg shadow-black/5">
        <li className="row-in flex items-center gap-3 bg-panel-2 px-3 py-2" style={{ animationDelay: '700ms' }}>
          <span className="w-12 font-mono text-xs text-ink">NVDA</span>
          <span className="text-ink-2"><mark className="bg-transparent font-semibold text-ink">NVIDIA</mark> Corp</span>
          <ArrowUpRight size={13} className="ml-auto text-muted" />
        </li>
      </ul>
    </div>
  )
}

// The original disclaimer: how the figures are read, which AI writes the analysis, and what kind of project this is.
function AboutProject() {
  return (
    <div className="mx-auto max-w-6xl px-5 pb-16 sm:px-8 sm:pb-24">
      <section aria-labelledby="about-heading" className="rounded-2xl border border-line bg-panel px-6 py-6 sm:px-8 sm:py-7">
        <h2 id="about-heading" className="mb-4 flex items-center gap-2 text-base font-semibold tracking-[-0.025em] text-ink">
          <Info size={16} className="text-accent" aria-hidden /> A passion project, with some rough edges
        </h2>
        <div className="grid gap-5 text-sm leading-relaxed text-ink-2 md:grid-cols-3 md:gap-8">
          <p>
            <span className="font-semibold text-ink">Parsed, not hand-checked.</span> Figures are read by code from the
            machine-readable tags in each filing, and every company tags a little differently. Some tables can look off: a
            blank cell, an oddly worded label, a period that is missing. Where the tool can tell why, a note under the table
            says so.
          </p>
          <p>
            <span className="font-semibold text-ink">Foreign companies are the hardest.</span> Companies outside the US
            file Forms 20-F, 40-F and 6-K, which follow looser rules than a US 10-K or 10-Q. Many report every six months, or
            put out their quarterly results in untagged press releases. Their pages can have more gaps and quirks than a US
            company's.
          </p>
          <p>
            <span className="font-semibold text-ink">Written by free-tier AI.</span> The analysis runs on Google&apos;s
            lightweight Gemini models at no cost. Every figure and quote is checked against the filings, but a more capable
            model would write sharper, more complete analysis. This is a personal project, not a commercial product, so
            treat it as a starting point and read the original filing before relying on anything here.
          </p>
        </div>
      </section>
    </div>
  )
}

function ClosingCta({ onPick, onSearch }) {
  return (
    <section className="mx-auto max-w-6xl px-5 pb-20 sm:px-8 sm:pb-28">
      <Reveal className={`${CARD} editorial-card relative overflow-hidden p-8 sm:p-12 lg:p-14`}>
        <div className="grid gap-10 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,0.8fr)] lg:items-center">
          <div>
            <h2 className="text-[clamp(2.4rem,5vw,3.6rem)] leading-[1.02] font-[620] tracking-[-0.045em] text-ink">Ready to read a filing?</h2>
            <p className="mt-4 max-w-md text-lg leading-relaxed text-ink-2">Search any SEC-registered company for its financials, what changed and a checked research memo.</p>
            <div className="mt-8 flex flex-wrap gap-3">
              <button type="button" onClick={onSearch} className={BTN_PRIMARY}>
                Search a company <ArrowRight size={16} className="transition-transform group-hover:translate-x-0.5" aria-hidden />
              </button>
              <button type="button" onClick={() => onPick('AAPL')} className={BTN_SECONDARY}>
                Try Apple <ArrowUpRight size={15} className="text-muted transition-colors group-hover:text-ink" aria-hidden />
              </button>
            </div>
          </div>
          <ul className="space-y-3.5 border-line text-[15px] text-ink-2 lg:border-l lg:pl-10">
            {['Free, no account needed', 'Every quote checked against the filing', 'Showcase companies load instantly', 'Original filing one click away'].map((t) => (
              <li key={t} className="flex items-center gap-3">
                <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-ink text-panel"><Check size={11} strokeWidth={3} /></span>
                {t}
              </li>
            ))}
          </ul>
        </div>
      </Reveal>
    </section>
  )
}

export default function Landing({ onPick, onSearch }) {
  return (
    <div className="landing">
      <CompanyMarquee onPick={onPick} />
      <Hero onPick={onPick} onSearch={onSearch} />
      <Showcase />
      <Process />
      <AboutProject />
      <ClosingCta onPick={onPick} onSearch={onSearch} />
    </div>
  )
}
