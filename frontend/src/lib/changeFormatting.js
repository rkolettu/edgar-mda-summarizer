export function formatChange(change, unit, formatSignedPct) {
  if (change === null || change === undefined) return null
  if (unit === 'ratio' || unit === 'points') return `${change > 0 ? '+' : ''}${(change * 100).toFixed(1)} pts`
  if (unit === 'days') return `${change > 0 ? '+' : ''}${Math.round(change)} days`
  return change >= 9 ? `${(1 + change).toFixed(0)}×` : formatSignedPct(change)
}
