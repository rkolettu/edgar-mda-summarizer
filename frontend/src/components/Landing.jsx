import { ArrowRight, ArrowUpRight } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import CandleField from './CandleField'

const HEADLINE_WORDS = ['numbers.', 'headlines.', 'footnotes.', 'guidance.']

const FACTS = [
  { value: '5 yrs', label: 'of financial trends', source: 'SEC XBRL' },
  { value: '7', label: 'research tabs per company', source: 'Overview → Changes' },
  { value: '3', label: 'annual forms read', source: '10-K · 20-F · 40-F' },
  { value: '1', label: 'quote behind every insight', source: 'Checked vs filing' },
  { value: '$0', label: 'to use, no sign-up', source: 'Free-tier AI' },
]

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
  { ticker: 'TD', name: 'Toronto-Dominion' },
  { ticker: 'HSBC', name: 'HSBC' },
  { ticker: 'SHEL', name: 'Shell' },
  { ticker: 'UBS', name: 'UBS' },
]

const CAPABILITIES = [
  {
    title: 'Five years of financials',
    body: 'Revenue, margins, free cash flow and buybacks read straight from each filing’s XBRL tags and charted across five fiscal years.',
    icon: BarsIcon,
  },
  {
    title: 'What management changed',
    body: 'Filing Changes ranks what this year’s report adds, rewrites or drops versus last year’s, numbers and wording, by materiality.',
    icon: DiffIcon,
  },
  {
    title: 'Quotes you can check',
    body: 'Every AI insight quotes one sentence from the filing. The quote is matched against the source, and figures that can’t be traced are underlined.',
    icon: QuoteIcon,
  },
  {
    title: 'Ask the filing',
    body: 'Ask a question in plain English. The answer comes from the stored filing passages and cites each one it used.',
    icon: HubIcon,
  },
  {
    title: 'Foreign filers, too',
    body: '20-F, 40-F and 6-K reports from UBS, HSBC, Shell, ASML and Canada’s banks, with a bank view of credit losses, efficiency and return on equity.',
    icon: GlobeIcon,
  },
]

const STEPS = [
  {
    title: 'Pick a company',
    body: 'Search by ticker or name. Any SEC registrant that files annual reports on EDGAR.',
    file: 'search.js',
    code: ['search("nvidia")', '', '// NVDA  NVIDIA Corp', '// 10-K, 10-Q and 8-K on EDGAR'],
    status: 'Found',
  },
  {
    title: 'Parse the filings',
    body: 'Code reads the latest annual report and recent quarters into structured facts. No model involved.',
    file: 'parse.js',
    code: ['parse(filing, {', "  source: 'inline XBRL',", '  years: 5,', '})', '', '// Revenue, margins, cash flow → stored'],
    status: 'Parsed',
  },
  {
    title: 'Check the analysis',
    body: 'AI writes the memo from those facts. Every quote and figure is matched back to the filing.',
    file: 'verify.js',
    code: ['verify(insight, filing)', '', '// Quote found in Item 7 MD&A', '// Figures traced to XBRL'],
    status: 'Verified',
  },
]

const STEP_MS = 5200

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

// Fades its children up the first time they scroll into view.
function Reveal({ as: Tag = 'div', delay = 0, className = '', children, ...rest }) {
  const ref = useRef(null)
  const [shown, setShown] = useState(false)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) {
        setShown(true)
        observer.disconnect()
      }
    }, { rootMargin: '0px 0px -8% 0px' })
    observer.observe(el)
    return () => observer.disconnect()
  }, [])
  return (
    <Tag ref={ref} className={`reveal ${shown ? 'is-shown' : ''} ${className}`} style={{ transitionDelay: `${delay}ms` }} {...rest}>
      {children}
    </Tag>
  )
}

function Eyebrow({ children, dark = false }) {
  return (
    <p className={`mb-6 flex items-center gap-3 font-mono text-[13px] ${dark ? 'text-white/55' : 'text-ink-2'}`}>
      <span aria-hidden className={`h-px w-8 ${dark ? 'bg-white/30' : 'bg-ink/30'}`} />
      {children}
    </p>
  )
}

function RotatingWord() {
  const reduced = usePrefersReducedMotion()
  const [index, setIndex] = useState(0)
  useEffect(() => {
    if (reduced) return
    const id = setInterval(() => setIndex((i) => (i + 1) % HEADLINE_WORDS.length), 2800)
    return () => clearInterval(id)
  }, [reduced])
  const word = HEADLINE_WORDS[index]
  return (
    <span className="whitespace-nowrap">
      the{' '}
      <span className="relative inline-block">
        <span key={word} className="word-in inline-block">{word}</span>
        <span aria-hidden key={`bar-${word}`} className="underline-in absolute right-[0.3em] -bottom-[0.06em] left-0 h-[0.09em] bg-ink/12" />
      </span>
    </span>
  )
}

function Hero({ onPick, onSearch }) {
  return (
    <section className="relative overflow-hidden">
      <div className="hero-grid pointer-events-none absolute inset-0" aria-hidden />
      <CandleField className="field-fade absolute top-0 right-[-18%] h-full w-[95%] opacity-45 sm:right-[-8%] sm:w-[70%] sm:opacity-100 lg:right-[-4%] lg:w-[62%]" />
      <div className="relative mx-auto max-w-6xl px-5 pt-16 pb-10 sm:px-8 sm:pt-24 lg:pt-28">
        <Reveal><Eyebrow>SEC EDGAR / Filing research</Eyebrow></Reveal>
        <Reveal as="h1" delay={80} className="font-display text-[clamp(2.9rem,10.5vw,8.6rem)] leading-[0.92] font-normal tracking-[-0.055em] text-ink">
          <span aria-hidden>
            Read beyond
            <br />
            <RotatingWord />
          </span>
          <span className="sr-only">Read beyond the numbers.</span>
        </Reveal>
        <div className="mt-10 grid gap-8 lg:mt-14 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end lg:gap-16">
          <Reveal as="p" delay={160} className="max-w-xl text-lg leading-relaxed text-ink-2 sm:text-xl">
            Start with a company. Follow the financials, see what management says changed, and trace each insight back to the filing.
          </Reveal>
          <Reveal delay={240} className="flex flex-wrap gap-3">
            <button type="button" onClick={onSearch} className="pill-primary group">
              Search a company <ArrowRight size={16} className="transition-transform group-hover:translate-x-0.5" aria-hidden />
            </button>
            <button type="button" onClick={() => onPick('NVDA')} className="pill-secondary">
              Try NVIDIA
            </button>
          </Reveal>
        </div>
      </div>
      <FactsMarquee />
    </section>
  )
}

function FactsMarquee() {
  const row = (hidden) => (
    <ul className="flex shrink-0 items-end gap-14 pr-14 sm:gap-20 sm:pr-20" aria-hidden={hidden || undefined}>
      {FACTS.map((f) => (
        <li key={f.label} className="flex shrink-0 items-end gap-4">
          <span className="font-display text-5xl leading-none tracking-[-0.05em] text-ink sm:text-6xl">{f.value}</span>
          <span className="pb-1 leading-tight">
            <span className="block text-sm text-ink-2">{f.label}</span>
            <span className="mt-1 block font-mono text-[11px] tracking-[0.08em] text-muted uppercase">{f.source}</span>
          </span>
        </li>
      ))}
    </ul>
  )
  return (
    <div className="marquee-mask relative border-t border-line/70 py-8">
      <div className="marquee flex w-max">
        {row(false)}
        {row(true)}
      </div>
    </div>
  )
}

function CompanyMarquee({ onPick }) {
  const row = (hidden) => (
    <ul className="flex shrink-0 items-center" aria-hidden={hidden || undefined}>
      {COMPANIES.map((c) => (
        <li key={c.ticker} className="shrink-0">
          <button
            type="button"
            tabIndex={hidden ? -1 : undefined}
            onClick={() => onPick(c.ticker)}
            className="group flex items-baseline gap-3 px-7 py-2 text-muted transition-colors hover:text-ink sm:px-10"
          >
            <span className="font-display text-2xl tracking-[-0.04em] sm:text-3xl">{c.name}</span>
            <span className="font-mono text-xs">{c.ticker}</span>
            <ArrowUpRight size={14} className="self-center opacity-0 transition-opacity group-hover:opacity-100" aria-hidden />
          </button>
        </li>
      ))}
    </ul>
  )
  return (
    <section aria-label="Try a company" className="border-y border-line/70 py-6">
      <div className="marquee-mask marquee-pause overflow-hidden">
        <div className="marquee marquee-slow flex w-max">
          {row(false)}
          {row(true)}
        </div>
      </div>
    </section>
  )
}

function Capabilities() {
  return (
    <section id="capabilities" className="mx-auto max-w-6xl px-5 py-24 sm:px-8 sm:py-32">
      <Reveal><Eyebrow>Capabilities</Eyebrow></Reveal>
      <Reveal as="h2" delay={80} className="font-display text-[clamp(2.5rem,6vw,4.6rem)] leading-[1.02] tracking-[-0.05em] text-ink">
        Everything in the filing.
        <br />
        <span className="text-ink/45">Nothing it doesn’t say.</span>
      </Reveal>
      <ol className="mt-16 sm:mt-24">
        {CAPABILITIES.map((c, i) => (
          <Reveal as="li" key={c.title} className="capability group border-b border-line/80 py-10 first:border-t sm:py-14">
            <div className="grid grid-cols-[2.5rem_minmax(0,1fr)] gap-x-4 sm:grid-cols-[4rem_minmax(0,1fr)_8rem] sm:gap-x-8">
              <span className="pt-2 font-mono text-xs text-muted">{String(i + 1).padStart(2, '0')}</span>
              <div>
                <h3 className="font-display text-3xl tracking-[-0.04em] text-ink transition-transform duration-500 group-hover:translate-x-2 sm:text-[2.6rem]">
                  {c.title}
                </h3>
                <p className="mt-3 max-w-xl text-base leading-relaxed text-ink-2 sm:text-lg">{c.body}</p>
              </div>
              <div className="hidden items-center justify-end text-ink sm:flex">
                <c.icon />
              </div>
            </div>
          </Reveal>
        ))}
      </ol>
    </section>
  )
}

function Process() {
  const reduced = usePrefersReducedMotion()
  const [active, setActive] = useState(0)
  const [cycle, setCycle] = useState(0)  // restarts the progress bar after a click

  useEffect(() => {
    if (reduced) return
    const id = setTimeout(() => setActive((a) => (a + 1) % STEPS.length), STEP_MS)
    return () => clearTimeout(id)
  }, [active, cycle, reduced])

  const step = STEPS[active]
  return (
    <section className="process-bg relative text-white">
      <div className="mx-auto max-w-6xl px-5 py-24 sm:px-8 sm:py-32">
        <Reveal><Eyebrow dark>Process</Eyebrow></Reveal>
        <Reveal as="h2" delay={80} className="font-display text-[clamp(2.5rem,6vw,4.6rem)] leading-[1.02] tracking-[-0.05em]">
          Three steps.
          <br />
          <span className="text-white/45">Every claim traced.</span>
        </Reveal>

        <div className="mt-16 grid gap-10 lg:mt-24 lg:grid-cols-2 lg:gap-16">
          <ol>
            {STEPS.map((s, i) => {
              const on = i === active
              return (
                <li key={s.title} className="border-b border-white/10">
                  <button
                    type="button"
                    aria-pressed={on}
                    onClick={() => {
                      setActive(i)
                      setCycle((c) => c + 1)
                    }}
                    className={`grid w-full grid-cols-[2.5rem_minmax(0,1fr)] gap-x-3 py-7 text-left transition-opacity duration-500 ${on ? 'opacity-100' : 'opacity-40 hover:opacity-70'}`}
                  >
                    <span className="pt-1.5 font-mono text-sm text-white/60">{['I', 'II', 'III'][i]}</span>
                    <span className={`transition-transform duration-500 ${on ? 'translate-x-2' : ''}`}>
                      <span className="block font-display text-2xl tracking-[-0.03em] sm:text-3xl">{s.title}</span>
                      <span className="mt-2 block text-sm leading-relaxed text-white/60 sm:text-base">{s.body}</span>
                      <span className="mt-5 block h-px w-full bg-white/10">
                        {on && <span key={`${active}-${cycle}`} className="step-progress block h-px bg-white" style={{ animationDuration: `${STEP_MS}ms` }} />}
                      </span>
                    </span>
                  </button>
                </li>
              )
            })}
          </ol>

          <div className="self-start overflow-hidden rounded-lg border border-white/12 bg-black/35 backdrop-blur-sm" aria-live="polite">
            <div className="flex items-center justify-between border-b border-white/10 px-5 py-3.5">
              <span className="flex gap-1.5" aria-hidden>
                <span className="h-2.5 w-2.5 rounded-full bg-white/20" />
                <span className="h-2.5 w-2.5 rounded-full bg-white/20" />
                <span className="h-2.5 w-2.5 rounded-full bg-white/20" />
              </span>
              <span className="font-mono text-xs text-white/45">{step.file}</span>
            </div>
            <pre key={active} className="code-in min-h-[15rem] overflow-x-auto px-5 py-6 font-mono text-[13px] leading-8 sm:text-sm">
              {step.code.map((line, i) => (
                <div key={i} className="flex gap-6" style={{ animationDelay: `${i * 90}ms` }}>
                  <span className="w-4 shrink-0 text-right text-white/25 select-none">{i + 1}</span>
                  <span className={line.startsWith('//') ? 'text-white/45' : 'text-white/90'}>{line || ' '}</span>
                </div>
              ))}
            </pre>
            <div className="flex items-center gap-2.5 border-t border-white/10 px-5 py-3.5 font-mono text-xs text-white/60">
              <span className="relative flex h-2 w-2">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60 motion-reduce:hidden" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-400" />
              </span>
              {step.status}
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}

function About() {
  return (
    <section aria-labelledby="about-heading" className="mx-auto max-w-6xl px-5 py-24 sm:px-8 sm:py-32">
      <Reveal><Eyebrow>About</Eyebrow></Reveal>
      <Reveal as="h2" id="about-heading" delay={80} className="font-display text-[clamp(2.5rem,6vw,4.6rem)] leading-[1.05] tracking-[-0.05em] text-ink">
        A passion project,
        <br />
        with some <span className="outlined">rough edges</span>
      </Reveal>
      <div className="mt-14 grid gap-10 text-[15px] leading-relaxed text-ink-2 md:grid-cols-3 md:gap-10">
        <Reveal delay={0} className="border-t border-ink/80 pt-5">
          <p className="mb-3 font-mono text-xs text-muted">01</p>
          <p>
            <span className="font-semibold text-ink">Parsed, not hand-checked.</span> Figures are read by code from the
            machine-readable tags in each filing, and every company tags a little differently. Some tables can look off: a
            blank cell, an oddly worded label, a period that is missing. Where the tool can tell why, a note under the table
            says so.
          </p>
        </Reveal>
        <Reveal delay={100} className="border-t border-ink/80 pt-5">
          <p className="mb-3 font-mono text-xs text-muted">02</p>
          <p>
            <span className="font-semibold text-ink">Foreign companies are the hardest.</span> Companies outside the US
            file Forms 20-F, 40-F and 6-K, which follow looser rules than a US 10-K or 10-Q. Many report every six months, or
            put out their quarterly results in untagged press releases. Their pages can have more gaps and quirks than a US
            company&apos;s.
          </p>
        </Reveal>
        <Reveal delay={200} className="border-t border-ink/80 pt-5">
          <p className="mb-3 font-mono text-xs text-muted">03</p>
          <p>
            <span className="font-semibold text-ink">Written by free-tier AI.</span> The analysis runs on Google&apos;s
            lightweight Gemini models at no cost. Every figure and quote is checked against the filings, but a more capable
            model would write sharper, more complete analysis. This is a personal project, not a commercial product, so
            treat it as a starting point and read the original filing before relying on anything here.
          </p>
        </Reveal>
      </div>
    </section>
  )
}

function ClosingCta({ onPick, onSearch }) {
  return (
    <section className="mx-auto max-w-6xl px-5 pb-24 sm:px-8 sm:pb-32">
      <Reveal className="relative overflow-hidden border border-ink/80 bg-panel/40">
        <CandleField shape="funnel" seed={11} className="field-fade absolute top-0 right-[-25%] h-full w-[90%] opacity-40 sm:right-0 sm:w-1/2 sm:opacity-100" />
        <span aria-hidden className="absolute bottom-0 left-0 h-24 w-24 border-t border-r border-line" />
        <div className="relative px-6 py-16 sm:px-14 sm:py-24">
          <h2 className="max-w-[14ch] font-display text-[clamp(2.4rem,5.5vw,4.2rem)] leading-[1.02] tracking-[-0.05em] text-ink">
            Ready to read a filing?
          </h2>
          <p className="mt-5 max-w-md text-lg leading-relaxed text-ink-2">
            Search any SEC-registered company and get its financials, changes and a checked research memo.
          </p>
          <div className="mt-9 flex flex-wrap gap-3">
            <button type="button" onClick={onSearch} className="pill-primary group">
              Search a company <ArrowRight size={16} className="transition-transform group-hover:translate-x-0.5" aria-hidden />
            </button>
            <button type="button" onClick={() => onPick('AAPL')} className="pill-secondary">
              Try Apple
            </button>
          </div>
          <p className="mt-6 font-mono text-xs text-muted">No account required</p>
        </div>
      </Reveal>
    </section>
  )
}

export default function Landing({ onPick, onSearch }) {
  return (
    <div className="landing">
      <Hero onPick={onPick} onSearch={onSearch} />
      <Capabilities />
      <CompanyMarquee onPick={onPick} />
      <Process />
      <About />
      <ClosingCta onPick={onPick} onSearch={onSearch} />
    </div>
  )
}

// Line illustrations for the capability rows; each animates while its row is hovered.

function BarsIcon() {
  return (
    <svg viewBox="0 0 120 100" className="cap-icon h-24 w-28" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden>
      <rect x="6" y="6" width="108" height="80" rx="3" />
      {[18, 32, 46, 60, 74, 88].map((x, i) => (
        <rect key={x} x={x} y={74 - (i + 2) * 7} width="9" height={(i + 2) * 7} fill="currentColor" stroke="none" className="cap-bar" style={{ opacity: 0.35 + i * 0.12, animationDelay: `${i * 70}ms` }} />
      ))}
      <circle cx="60" cy="95" r="2" fill="currentColor" stroke="none" />
    </svg>
  )
}

function DiffIcon() {
  return (
    <svg viewBox="0 0 120 100" className="cap-icon h-24 w-28" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden>
      <rect x="6" y="6" width="108" height="88" rx="3" />
      <path d="M18 24h10M23 19v10" />
      <path d="M36 24h60" strokeWidth="5" className="cap-line" />
      <path d="M18 46h10" />
      <path d="M36 46h44" strokeWidth="5" opacity="0.35" strokeDasharray="4 3" />
      <path d="M18 68h10M23 63v10" />
      <path d="M36 68h52" strokeWidth="5" className="cap-line" style={{ animationDelay: '120ms' }} />
    </svg>
  )
}

function QuoteIcon() {
  return (
    <svg viewBox="0 0 120 100" className="cap-icon h-24 w-28" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden>
      <path d="M10 14h100v58H52l-18 16V72H10z" />
      <path d="M26 32c-4 0-6 3-6 7s3 6 6 6c0 4-2 7-6 8M44 32c-4 0-6 3-6 7s3 6 6 6c0 4-2 7-6 8" />
      <circle cx="86" cy="43" r="13" />
      <path d="M80 43l4.5 4.5L93 38" className="cap-check" strokeWidth="2" />
    </svg>
  )
}

function HubIcon() {
  const nodes = [[60, 12], [96, 30], [96, 70], [60, 88], [24, 70], [24, 30]]
  return (
    <svg viewBox="0 0 120 100" className="cap-icon cap-spin h-24 w-28" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden>
      <circle cx="60" cy="50" r="26" opacity="0.4" />
      {nodes.map(([x, y]) => (
        <g key={`${x}-${y}`}>
          <path d={`M60 50L${x} ${y}`} opacity="0.6" />
          <circle cx={x} cy={y} r="6" fill="var(--color-page)" />
        </g>
      ))}
      <circle cx="60" cy="50" r="11" fill="currentColor" />
    </svg>
  )
}

function GlobeIcon() {
  return (
    <svg viewBox="0 0 120 100" className="cap-icon h-24 w-28" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden>
      <circle cx="60" cy="50" r="40" />
      <ellipse cx="60" cy="50" rx="17" ry="40" className="cap-meridian" />
      <path d="M20 50h80M26 30h68M26 70h68" opacity="0.5" />
    </svg>
  )
}
