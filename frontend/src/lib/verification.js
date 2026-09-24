import { useState } from 'react'

export function itemStatus(item) {
  return item.status ?? (item.verified ? 'verified' : 'unverified')
}

export function figureCounts(item) {
  const spans = [...(item.figures?.headline ?? []), ...(item.figures?.detail ?? [])]
  return { total: spans.length, untraced: spans.filter((s) => !s.verified).length }
}

export function dimIfUnverified(item) {
  return itemStatus(item) === 'unverified' ? 'opacity-55' : ''
}

// Unverified items (quote not found in the filing) are hidden until the reader asks for them.
export function useVerifiedItems(items) {
  const [showUnverified, setShowUnverified] = useState(false)
  const unverifiedCount = items.filter((i) => itemStatus(i) === 'unverified').length
  return {
    visible: showUnverified ? items : items.filter((i) => itemStatus(i) !== 'unverified'),
    unverifiedCount,
    showUnverified,
    toggle: () => setShowUnverified((v) => !v),
  }
}
