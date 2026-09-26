import { ExternalLink, Loader2, MessageSquare, Send, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { postJson } from '../lib/api'
import { STATUS } from '../lib/colors'

const SUGGESTIONS = [
  'What are the biggest new risks in the latest filing?',
  'What changed in commitments and guarantees?',
  'How does management explain revenue growth?',
  'What does management say about the outlook?',
]

// The answer's text with citations as chips and figures the check could not trace underlined.
function AnswerText({ text, figures, onCite }) {
  const marks = [
    ...(figures ?? []).filter((f) => !f.verified).map((f) => ({ start: f.start, end: f.end, kind: 'figure' })),
    ...[...text.matchAll(/\[(S\d+|F)\]/g)].map((m) => ({ start: m.index, end: m.index + m[0].length, kind: 'cite', id: m[1] })),
  ].sort((a, b) => a.start - b.start)
  const parts = []
  let cursor = 0
  for (const mark of marks) {
    if (mark.start < cursor) continue
    parts.push(text.slice(cursor, mark.start))
    if (mark.kind === 'figure') {
      parts.push(
        <mark key={mark.start} title="Not found in the figures or passages the answer was given"
          className="bg-transparent text-inherit underline decoration-dotted decoration-2 underline-offset-4"
          style={{ textDecorationColor: STATUS.warning }}>
          {text.slice(mark.start, mark.end)}
        </mark>,
      )
    } else {
      parts.push(
        mark.id === 'F'
          ? <sup key={mark.start} className="ml-0.5 text-[10px] text-muted" title="From the filings' tagged figures">fig</sup>
          : (
            <button key={mark.start} type="button" onClick={() => onCite(mark.id)}
              className="mx-0.5 rounded border border-line bg-panel px-1 font-mono text-[10px] text-accent align-[1px] hover:border-accent">
              {mark.id}
            </button>
          ),
      )
    }
    cursor = mark.end
  }
  parts.push(text.slice(cursor))
  return <p className="text-sm leading-relaxed whitespace-pre-line text-ink">{parts}</p>
}

function Sources({ sources, open, onToggle }) {
  if (!sources?.length) return null
  return (
    <ul className="mt-2 space-y-1.5">
      {sources.map((s) => (
        <li key={s.id} className="text-xs">
          <button type="button" onClick={() => onToggle(s.id)} aria-expanded={open === s.id}
            className="flex w-full items-start gap-1.5 text-left text-ink-2 hover:text-ink">
            <span className="font-mono text-accent">{s.id}</span> <span>{s.label}</span>
          </button>
          {open === s.id && (
            <div className="mt-1.5 border-l-2 border-line pl-3 leading-relaxed text-ink-2">
              <p className="italic">“{s.text}”</p>
              {s.document_url && (
                <a href={s.document_url} target="_blank" rel="noreferrer" className="mt-1 inline-flex items-center gap-1 text-accent hover:text-accent-hover">
                  Open the filing <ExternalLink size={11} />
                </a>
              )}
            </div>
          )}
        </li>
      ))}
    </ul>
  )
}

function Message({ message }) {
  const [open, setOpen] = useState(null)
  if (message.role === 'user') {
    return <p className="ml-auto max-w-[85%] rounded-xl bg-ink px-3.5 py-2 text-sm text-panel">{message.content}</p>
  }
  return (
    <div className="max-w-full">
      <AnswerText text={message.content} figures={message.figures} onCite={(id) => setOpen(open === id ? null : id)} />
      <Sources sources={message.sources} open={open} onToggle={(id) => setOpen(open === id ? null : id)} />
    </div>
  )
}

// A chat about the company's stored filings: answers come from the filing passages that match each question.
// Keyed by ticker where it is rendered, so a new company starts a new conversation.
export default function FilingChat({ research }) {
  const ticker = research.company.ticker
  const [open, setOpen] = useState(false)
  const [messages, setMessages] = useState([])
  const [draft, setDraft] = useState('')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState(null)
  const bottom = useRef(null)
  const input = useRef(null)

  useEffect(() => {
    bottom.current?.scrollIntoView({ block: 'end' })
  }, [messages, pending])
  useEffect(() => {
    if (open) input.current?.focus()
  }, [open])

  async function ask(question) {
    const q = question.trim()
    if (!q || pending) return
    const history = messages.map(({ role, content }) => ({ role, content }))
    setMessages((m) => [...m, { role: 'user', content: q }])
    setDraft('')
    setPending(true)
    setError(null)
    try {
      const res = await postJson(`/api/research/${encodeURIComponent(ticker)}/chat`, { question: q, history })
      setMessages((m) => [...m, { role: 'assistant', content: res.answer, sources: res.sources, figures: res.figures }])
    } catch (err) {
      setError(err.message || 'The question could not be answered.')
    } finally {
      setPending(false)
    }
  }

  if (!open) {
    return (
      <button type="button" onClick={() => setOpen(true)}
        className="fixed right-5 bottom-5 z-30 inline-flex items-center gap-2 rounded-full bg-ink px-4 py-3 text-sm font-medium text-panel shadow-lg hover:bg-ink/90">
        <MessageSquare size={16} aria-hidden /> Ask about this filing
      </button>
    )
  }
  return (
    <section aria-label={`Questions about ${ticker}'s filings`}
      className="fixed inset-0 z-40 flex flex-col border-line bg-panel shadow-2xl sm:inset-auto sm:right-5 sm:bottom-5 sm:h-[min(640px,calc(100vh-40px))] sm:w-[420px] sm:rounded-2xl sm:border">
      <header className="flex items-start gap-3 border-b border-line px-5 py-4">
        <div className="min-w-0 flex-1">
          <h2 className="text-base font-semibold tracking-[-0.02em] text-ink">Ask about {ticker}&apos;s filings</h2>
          <p className="mt-0.5 text-xs text-muted">Answers use the stored filings and cite the passages they rest on.</p>
        </div>
        <button type="button" onClick={() => setOpen(false)} aria-label="Close the chat" className="rounded p-1 text-muted hover:text-ink">
          <X size={18} />
        </button>
      </header>
      <div className="flex-1 space-y-4 overflow-y-auto px-5 py-4" aria-live="polite">
        {messages.length === 0 && (
          <div>
            <p className="mb-2 text-xs text-muted">Try asking</p>
            <div className="flex flex-col items-start gap-2">
              {SUGGESTIONS.map((s) => (
                <button key={s} type="button" onClick={() => ask(s)}
                  className="rounded-lg border border-line px-3 py-2 text-left text-sm text-ink-2 hover:border-ink hover:text-ink">
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m, i) => <Message key={i} message={m} />)}
        {pending && (
          <p className="flex items-center gap-2 text-xs text-muted" role="status">
            <Loader2 size={13} className="motion-safe:animate-spin" aria-hidden /> Reading the filing passages…
          </p>
        )}
        {error && <p className="text-xs" style={{ color: STATUS.critical }} role="alert">{error}</p>}
        <div ref={bottom} />
      </div>
      <form className="flex items-end gap-2 border-t border-line px-4 py-3" onSubmit={(e) => { e.preventDefault(); ask(draft) }}>
        <label htmlFor="filing-chat-input" className="sr-only">Your question</label>
        <textarea id="filing-chat-input" ref={input} value={draft} rows={1} maxLength={500}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); ask(draft) } }}
          placeholder="Ask a question about the filing"
          className="max-h-32 min-h-10 flex-1 resize-none rounded-lg border border-line bg-page px-3 py-2 text-sm text-ink outline-none focus:border-accent" />
        <button type="submit" disabled={pending || !draft.trim()} aria-label="Send"
          className="inline-flex h-10 w-10 items-center justify-center rounded-lg bg-ink text-panel disabled:opacity-40">
          <Send size={15} />
        </button>
      </form>
      <p className="px-5 pb-3 text-[11px] text-muted">AI answers can be wrong; check the cited passages. Not investment advice.</p>
    </section>
  )
}
