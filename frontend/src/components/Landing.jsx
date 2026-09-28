import { ArrowRight, ArrowUpRight, Check, Search } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

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

const FACTS = [
  { value: 5, label: 'Years of financial history' },
  { value: 7, label: 'Research tabs per company' },
  { value: 5, label: 'SEC form types read' },
  { value: 1, label: 'Filing quote behind every insight' },
]

const STEPS = [
  { key: 'search', label: 'Search', title: 'Pick any SEC registrant', body: 'Type a ticker or a name. Every company that files annual reports on EDGAR is searchable.' },
  { key: 'parse', label: 'Parse', title: 'Filings become structured facts', body: 'Code reads the latest annual report and recent quarters once and stores them. No model is involved in the numbers.' },
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
    <section className="mx-auto grid max-w-6xl items-center gap-14 px-5 pt-14 pb-16 sm:px-8 sm:pt-20 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)] lg:gap-12 lg:pt-24 lg:pb-24">
      <div>
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
      <HeroCollage />
    </section>
  )
}

// Three cards from the product (a filing passage, a trend chart, filing changes) that float and follow the pointer.
function HeroCollage() {
  const ref = useRef(null)
  const reduced = usePrefersReducedMotion()

  useEffect(() => {
    const el = ref.current
    if (!el || reduced) return
    let frame = 0
    const onMove = (e) => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => {
        el.style.setProperty('--mx', (e.clientX / window.innerWidth - 0.5).toFixed(3))
        el.style.setProperty('--my', (e.clientY / window.innerHeight - 0.5).toFixed(3))
      })
    }
    window.addEventListener('pointermove', onMove, { passive: true })
    return () => {
      cancelAnimationFrame(frame)
      window.removeEventListener('pointermove', onMove)
    }
  }, [reduced])

  return (
    <Reveal delay={200} className="collage relative mx-auto h-[400px] w-full max-w-[520px] sm:h-[460px]" aria-hidden>
      <div ref={ref} className="absolute inset-0">
        <div className="parallax absolute top-0 right-0 w-[80%]" style={{ '--depth': '14px' }}>
          <div className={`${CARD} float editorial-card p-5`} style={{ '--float-delay': '0s' }}>
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
        </div>

        <div className="parallax absolute top-[43%] left-0 w-[64%]" style={{ '--depth': '26px' }}>
          <div className={`${CARD} float p-5 shadow-[0_24px_60px_-20px_rgba(36,31,24,0.25)]`} style={{ '--float-delay': '-2s' }}>
            <div className="mb-3 flex items-center justify-between">
              <span className={`${LABEL} text-muted`}>Five-year trend</span>
              <span className="flex gap-2.5 text-[10px] text-ink-2">
                <span className="flex items-center gap-1"><span className="h-1.5 w-1.5 rounded-full bg-[#355e99]" />Revenue</span>
                <span className="flex items-center gap-1"><span className="h-1.5 w-1.5 rounded-full bg-[#c8702a]" />FCF</span>
              </span>
            </div>
            <TrendSvg />
          </div>
        </div>

        <div className="parallax absolute right-[2%] bottom-0 w-[46%]" style={{ '--depth': '38px' }}>
          <div className={`${CARD} float p-4 shadow-[0_24px_60px_-20px_rgba(36,31,24,0.25)]`} style={{ '--float-delay': '-4s' }}>
            <span className={`${LABEL} text-muted`}>Filing changes</span>
            <ul className="mt-3 space-y-2 text-[12px] text-ink-2">
              <ChangeRow sign="+" color="#287252" label="New risk factor" w="85%" />
              <ChangeRow sign="~" color="#946819" label="Guidance reworded" w="60%" />
              <ChangeRow sign="−" color="#a43e39" label="Segment dropped" w="40%" />
            </ul>
          </div>
        </div>
      </div>
    </Reveal>
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

function CountUp({ value, start }) {
  const reduced = usePrefersReducedMotion()
  const [n, setN] = useState(reduced ? value : 0)
  useEffect(() => {
    if (!start || reduced) return
    let frame = 0
    const t0 = performance.now()
    const tick = (now) => {
      const p = Math.min(1, (now - t0) / 1100)
      setN(Math.round(value * (1 - Math.pow(1 - p, 3))))
      if (p < 1) frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [start, value, reduced])
  return n
}

function Facts() {
  const [ref, inView] = useInView()
  return (
    <section className="mx-auto max-w-6xl px-5 sm:px-8">
      <dl ref={ref} className="grid grid-cols-2 border-y border-line lg:grid-cols-4">
        {FACTS.map((f, i) => (
          <div key={f.label} className={`flex flex-col py-7 sm:py-9 ${i % 2 ? 'pl-5 sm:pl-8' : 'pr-5 sm:pr-8'} ${i % 2 ? 'border-l border-line' : ''} ${i >= 2 ? 'border-t border-line lg:border-t-0' : ''} ${i === 2 ? 'lg:border-l lg:pl-8' : ''}`}>
            <dt className={`order-2 mt-2 ${LABEL} leading-snug text-muted`}>{f.label}</dt>
            <dd className="text-5xl font-[650] tracking-[-0.06em] text-ink tabular-nums sm:text-6xl">
              <CountUp value={f.value} start={inView} />
            </dd>
          </div>
        ))}
      </dl>
    </section>
  )
}

function CompanyMarquee({ onPick }) {
  const row = (hidden) => (
    <ul className="flex shrink-0 gap-3 pr-3" aria-hidden={hidden || undefined}>
      {COMPANIES.map((c) => (
        <li key={c.ticker} className="shrink-0">
          <button
            type="button"
            tabIndex={hidden ? -1 : undefined}
            onClick={() => onPick(c.ticker)}
            className="group flex items-center gap-3 rounded-xl border border-line bg-panel px-4 py-3 transition-colors hover:border-ink"
          >
            <span className="font-mono text-xs font-medium text-ink">{c.ticker}</span>
            <span className="text-sm text-ink-2">{c.name}</span>
            <ArrowUpRight size={14} className="text-muted transition-colors group-hover:text-ink" aria-hidden />
          </button>
        </li>
      ))}
    </ul>
  )
  return (
    <section aria-label="Try a company" className="py-14 sm:py-16">
      <div className="mx-auto mb-5 flex max-w-6xl items-baseline justify-between gap-4 px-5 sm:px-8">
        <p className={`${LABEL} text-muted`}>Try a company</p>
        <p className="hidden text-xs text-muted sm:block">Showcase companies load instantly. Others take about a minute the first time.</p>
      </div>
      <div className="marquee-mask marquee-pause">
        <div className="marquee flex w-max">
          {row(false)}
          {row(true)}
        </div>
      </div>
    </section>
  )
}

const FEATURES = [
  {
    label: 'Financials',
    title: 'Five years of financials',
    body: 'Revenue, margins, free cash flow and buybacks, read from each filing’s XBRL tags and charted across five fiscal years.',
    span: 'lg:col-span-4',
    art: () => <TrendSvg className="h-36 w-full sm:h-40" />,
  },
  {
    label: 'Verification',
    title: 'Quotes you can check',
    body: 'Every insight quotes the filing. Figures that can’t be traced are underlined.',
    span: 'lg:col-span-2',
    art: QuoteArt,
  },
  {
    label: 'Filing changes',
    title: 'What management changed',
    body: 'What this year’s report adds, rewrites or drops versus last year’s, ranked by materiality.',
    span: 'lg:col-span-2',
    art: ChangesArt,
  },
  {
    label: 'Q&A',
    title: 'Ask the filing',
    body: 'Ask in plain English. Answers cite the filing passages they came from.',
    span: 'lg:col-span-2',
    art: ChatArt,
  },
  {
    label: 'Foreign filers',
    title: 'Beyond the 10-K',
    body: '20-F, 40-F and 6-K reports, with a bank view of credit losses, efficiency and return on equity.',
    span: 'lg:col-span-2',
    art: FormsArt,
  },
]

function Features() {
  return (
    <section className="mx-auto max-w-6xl px-5 py-16 sm:px-8 sm:py-24">
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,0.6fr)] lg:items-end lg:gap-16">
        <Reveal>
          <SectionLabel>What you get</SectionLabel>
          <h2 className="text-[clamp(2.4rem,5vw,3.6rem)] leading-[1.02] font-[620] tracking-[-0.045em] text-ink">
            Everything in the filing.
            <br className="hidden sm:block" /> <span className="text-ink/35">Nothing it doesn’t say.</span>
          </h2>
        </Reveal>
        <Reveal as="p" delay={80} className="max-w-md text-lg leading-relaxed text-ink-2 lg:justify-self-end">
          Each company page is built from its own filings, with the source a click away.
        </Reveal>
      </div>
      <div className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-6">
        {FEATURES.map((f, i) => (
          <Reveal key={f.title} delay={(i % 3) * 70} className={`feature ${CARD} flex flex-col p-6 transition-[transform,box-shadow] duration-500 hover:-translate-y-1 hover:shadow-[0_24px_50px_-24px_rgba(36,31,24,0.25)] sm:p-7 ${f.span} ${i === 0 ? 'sm:col-span-2' : ''}`}>
            <div className={`mb-6 flex items-center justify-between ${LABEL} text-muted`}>
              <span>{f.label}</span>
              <span className="font-mono tracking-normal">{String(i + 1).padStart(2, '0')}</span>
            </div>
            <div className={i === 0 ? 'grid flex-1 gap-8 md:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)] md:items-end' : 'flex flex-1 flex-col'}>
              <div>
                <h3 className="text-2xl font-[620] tracking-[-0.045em] text-ink sm:text-[1.7rem]">{f.title}</h3>
                <p className="mt-2 text-[15px] leading-relaxed text-ink-2">{f.body}</p>
              </div>
              <div className={i === 0 ? '' : 'mt-7 flex flex-1 items-end'}><f.art /></div>
            </div>
          </Reveal>
        ))}
      </div>
    </section>
  )
}

function QuoteArt() {
  return (
    <div className="w-full border-l-2 border-line pl-4">
      <p className={`${LABEL} text-[10px] text-muted`}>From the filing</p>
      <div className="mt-2.5 space-y-2">
        <Line w="100%" />
        <Line w="78%" />
      </div>
      <div className="badge-pop mt-3.5 inline-flex items-center gap-1.5 rounded-md bg-[#287252]/10 px-2 py-1 text-[11px] font-semibold text-[#287252]">
        <Check size={12} strokeWidth={3} /> Quote found
      </div>
    </div>
  )
}

function ChangesArt() {
  return (
    <ul className="w-full space-y-2.5 text-[13px] text-ink-2">
      <ChangeRow sign="+" color="#287252" label="Added" w="80%" />
      <ChangeRow sign="~" color="#946819" label="Rewritten" w="55%" />
      <ChangeRow sign="−" color="#a43e39" label="Dropped" w="30%" />
    </ul>
  )
}

function ChatArt() {
  return (
    <div className="w-full space-y-2.5 text-[12px]">
      <div className="bubble-in ml-auto w-fit max-w-[85%] rounded-xl rounded-br-sm bg-ink px-3 py-2 text-panel">What drove the margin change?</div>
      <div className="bubble-in w-[88%] rounded-xl rounded-bl-sm bg-panel-2 px-3 py-2.5" style={{ animationDelay: '350ms' }}>
        <div className="space-y-1.5">
          <Line w="100%" />
          <Line w="70%" />
        </div>
        <div className="mt-2 flex gap-1.5 font-mono text-[10px] text-accent">
          <span className="rounded border border-accent/30 px-1">[1]</span>
          <span className="rounded border border-accent/30 px-1">[2]</span>
        </div>
      </div>
    </div>
  )
}

function FormsArt() {
  return (
    <div className="w-full">
      <div className="flex flex-wrap gap-1.5">
        {['10-K', '10-Q', '20-F', '40-F', '6-K'].map((f, i) => (
          <span key={f} className="chip-in rounded-md border border-line bg-panel-2 px-2 py-1 font-mono text-[11px] text-ink" style={{ animationDelay: `${i * 70}ms` }}>{f}</span>
        ))}
      </div>
      <p className={`mt-3 ${LABEL} text-[10px] leading-relaxed text-muted`}>Bank view: credit losses · cost/income · ROE</p>
    </div>
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
          <div ref={ref} className="grid grid-cols-3 border-b border-line" role="tablist" aria-label="Process steps">
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
                className={`relative px-4 py-4 text-left transition-colors sm:px-6 ${i ? 'border-l border-line' : ''} ${i === active ? 'bg-panel' : 'bg-panel-2 hover:bg-panel'}`}
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
              <div className="mt-7 min-h-[11.5rem] rounded-xl border border-line bg-panel-2 p-5">
                {step.key === 'search' && <SearchPreview />}
                {step.key === 'parse' && <ParsePreview />}
                {step.key === 'verify' && <VerifyPreview />}
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
    <div className="mx-auto max-w-sm">
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

function ParsePreview() {
  const rows = ['Income statement', 'Cash flow statement', 'Segments', 'Notes and commitments', 'Latest quarter']
  return (
    <ul className="grid gap-x-8 gap-y-2.5 text-[13px] sm:grid-cols-2">
      {rows.map((r, i) => (
        <li key={r} className="row-in flex items-center justify-between gap-3 border-b border-line/70 pb-2.5" style={{ animationDelay: `${i * 160}ms` }}>
          <span className="text-ink-2">{r}</span>
          <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-[#287252]"><Check size={12} strokeWidth={3} /> Stored</span>
        </li>
      ))}
      <li className="row-in self-end font-mono text-[11px] text-muted" style={{ animationDelay: `${rows.length * 160}ms` }}>Source: inline XBRL</li>
    </ul>
  )
}

function VerifyPreview() {
  return (
    <div>
      <div className="space-y-2">
        <Line w="70%" dark />
        <Line w="94%" />
        <div className="flex items-center gap-2">
          <Line w="38%" />
          <span className="h-2 w-10 border-b-2 border-dotted border-[#946819]" />
          <Line w="30%" />
        </div>
      </div>
      <div className="mt-4 border-l-2 border-line pl-4">
        <p className={`${LABEL} text-[10px] text-muted`}>Source quote</p>
        <div className="mt-2 space-y-1.5"><Line w="100%" /><Line w="64%" /></div>
      </div>
      <div className="mt-4 flex flex-wrap gap-2 text-[11px] font-semibold">
        <span className="row-in inline-flex items-center gap-1.5 rounded-md bg-[#287252]/10 px-2 py-1 text-[#287252]" style={{ animationDelay: '300ms' }}>
          <Check size={12} strokeWidth={3} /> Quote found in filing
        </span>
        <span className="row-in inline-flex items-center gap-1.5 rounded-md bg-[#946819]/10 px-2 py-1 text-[#946819]" style={{ animationDelay: '500ms' }}>
          1 figure not traced, underlined
        </span>
      </div>
    </div>
  )
}

const NOTES = [
  {
    label: 'Parsed, not hand-checked',
    body: 'Figures are read by code from the machine-readable tags in each filing, and every company tags a little differently. Some tables can look off: a blank cell, an oddly worded label, a period that is missing. Where the tool can tell why, a note under the table says so.',
  },
  {
    label: 'Foreign companies are the hardest',
    body: 'Companies outside the US file Forms 20-F, 40-F and 6-K, which follow looser rules than a US 10-K or 10-Q. Many report every six months, or put out their quarterly results in untagged press releases. Their pages can have more gaps and quirks than a US company’s.',
  },
  {
    label: 'Written by free-tier AI',
    body: 'The analysis runs on Google’s lightweight Gemini models at no cost. Every figure and quote is checked against the filings, but a more capable model would write sharper, more complete analysis. This is a personal project, not a commercial product, so treat it as a starting point and read the original filing before relying on anything here.',
  },
]

function About() {
  return (
    <section aria-labelledby="about-heading" className="border-t border-line">
      <div className="mx-auto max-w-6xl px-5 py-16 sm:px-8 sm:py-24">
        <Reveal>
          <SectionLabel>About this project</SectionLabel>
          <h2 id="about-heading" className="max-w-3xl text-[clamp(2.4rem,5vw,3.6rem)] leading-[1.02] font-[620] tracking-[-0.045em] text-ink">
            A passion project, with some{' '}
            <span className="relative inline-block whitespace-nowrap">
              rough edges.
              <svg viewBox="0 0 300 16" preserveAspectRatio="none" className="scribble absolute -bottom-2 left-0 h-3 w-[96%] text-accent" aria-hidden>
                <path d="M3 11 C 50 3, 90 14, 140 8 S 230 3, 297 9" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" pathLength="1" />
              </svg>
            </span>
          </h2>
        </Reveal>
        <div className="mt-12 grid gap-8 md:grid-cols-3 md:gap-6">
          {NOTES.map((n, i) => (
            <Reveal key={n.label} delay={i * 90} className="border-l-2 border-line pl-5">
              <p className={`${LABEL} text-ink-2`}>{n.label}</p>
              <p className="mt-3 text-[15px] leading-relaxed text-ink-2">{n.body}</p>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
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
      <Hero onPick={onPick} onSearch={onSearch} />
      <Facts />
      <CompanyMarquee onPick={onPick} />
      <Features />
      <Process />
      <About />
      <ClosingCta onPick={onPick} onSearch={onSearch} />
    </div>
  )
}
