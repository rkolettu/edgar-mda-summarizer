// Chart values arrive in USD billions (per the system prompt's "$109.1B" convention).
export function formatBillions(value) {
  const abs = Math.abs(value)
  if (abs === 0) return '$0'
  if (abs >= 1000) return `$${(value / 1000).toFixed(2)}T`
  if (abs >= 1) return `$${value.toFixed(1)}B`
  return `$${Math.round(value * 1000)}M`
}

export function formatPercent(part, total) {
  if (!total) return '0%'
  return `${((part / total) * 100).toFixed(1)}%`
}
