export function formatUsd(value, { digits } = {}) {
  if (value === null || value === undefined) return '—'
  const abs = Math.abs(value)
  const sign = value < 0 ? '-' : ''
  if (abs === 0) return '$0'
  if (abs >= 1e12) return `${sign}$${(abs / 1e12).toFixed(digits ?? 2)}T`
  if (abs >= 1e9) return `${sign}$${(abs / 1e9).toFixed(digits ?? 1)}B`
  if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(digits ?? 0)}M`
  return `${sign}$${abs.toLocaleString('en-US', { maximumFractionDigits: 2 })}`
}

export function formatPct(fraction, digits = 1) {
  if (fraction === null || fraction === undefined) return '—'
  return `${(fraction * 100).toFixed(digits)}%`
}

export function formatSignedPct(fraction, digits = 1) {
  if (fraction === null || fraction === undefined) return '—'
  const sign = fraction > 0 ? '+' : ''
  return `${sign}${(fraction * 100).toFixed(digits)}%`
}

export function formatShare(part, total) {
  return total ? formatPct(part / total) : '0%'
}

export function formatEps(value) {
  if (value === null || value === undefined) return '—'
  return `$${value.toFixed(2)}`
}

export function fiscalYearLabel(periodEnd) {
  return periodEnd ? `FY${periodEnd.slice(0, 4)}` : 'FY'
}
