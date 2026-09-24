import { CircleAlert, CircleCheck, Eye, EyeOff } from 'lucide-react'
import { STATUS } from '../lib/colors'
import { figureCounts, itemStatus } from '../lib/verification'

// Renders model-written text with any figure that couldn't be traced to the filing or SEC data marked inline.
export function FigureText({ text, spans }) {
  const untraced = (spans ?? []).filter((s) => !s.verified)
  if (!untraced.length) return text
  const parts = []
  let cursor = 0
  for (const s of untraced) {
    if (s.start > cursor) parts.push(text.slice(cursor, s.start))
    parts.push(
      <mark
        key={s.start}
        title="Not found in the filing text or SEC financial data"
        className="bg-transparent text-inherit underline decoration-dotted decoration-2 underline-offset-4"
        style={{ textDecorationColor: STATUS.warning }}
      >
        {text.slice(s.start, s.end)}
      </mark>,
    )
    cursor = s.end
  }
  parts.push(text.slice(cursor))
  return parts
}

function evidenceLabel(item, where) {
  const status = itemStatus(item)
  const { total, untraced } = figureCounts(item)
  const noun = (n) => (n === 1 ? 'figure' : 'figures')
  if (status === 'unverified') return item.evidence ? `Quote not found verbatim in ${where}` : 'No source quote provided'
  if (status === 'partial') return `Quote verified · ${untraced} of ${total} ${noun(total)} not found in ${where} or SEC data`
  return total ? `Quote and all ${total} ${noun(total)} verified in ${where} or SEC data` : `Quote verified in ${where}`
}

export function Evidence({ item, where = 'filing' }) {
  const verified = itemStatus(item) === 'verified'
  const Icon = verified ? CircleCheck : CircleAlert
  const icon = <Icon size={13} className="shrink-0" style={{ color: verified ? STATUS.good : STATUS.warning }} aria-hidden />
  const label = evidenceLabel(item, where)

  if (!item.evidence) {
    return (
      <p className="mt-2 flex items-center gap-1.5 text-xs text-muted">
        {icon}
        {label}
      </p>
    )
  }
  return (
    <details className="group mt-2 text-xs">
      <summary className="flex w-fit cursor-pointer list-none flex-wrap items-center gap-1.5 text-muted select-none hover:text-ink-2">
        {icon}
        {label}
        <span className="text-accent group-open:hidden">· Show source</span>
        <span className="hidden text-accent group-open:inline">· Hide source</span>
      </summary>
      <blockquote className="mt-2 border-l-2 border-line pl-3 leading-relaxed text-ink-2 italic">“{item.evidence}”</blockquote>
    </details>
  )
}

export function UnverifiedToggle({ count, shown, onToggle, className = '' }) {
  if (!count) return null
  const Icon = shown ? EyeOff : Eye
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-expanded={shown}
      className={`flex items-center gap-1.5 py-3 text-xs text-muted hover:text-ink-2 ${className}`}
    >
      <Icon size={13} aria-hidden />
      {shown ? `Hide ${count} unverified` : `${count} unverified ${count === 1 ? 'item' : 'items'} hidden · Show`}
    </button>
  )
}
