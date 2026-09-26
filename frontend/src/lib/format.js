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

const CURRENCY_PREFIX = {
  USD: '$', EUR: '€', GBP: '£', JPY: '¥', CNY: 'RMB ', TWD: 'NT$', CAD: 'C$', HKD: 'HK$', AUD: 'A$',
  BRL: 'R$', INR: '₹', KRW: '₩', CHF: 'CHF ', DKK: 'DKK ',
}

export function currencyPrefix(currency) {
  return CURRENCY_PREFIX[currency] ?? (currency ? `${currency} ` : '')
}

// Amounts in the filer's reporting currency; the research views never convert currencies.
export function formatMoney(value, currency = 'USD', { digits } = {}) {
  if (value === null || value === undefined) return '—'
  const prefix = currencyPrefix(currency)
  const abs = Math.abs(value)
  const sign = value < 0 ? '−' : ''
  if (abs === 0) return `${prefix}0`
  if (abs >= 1e12) return `${sign}${prefix}${(abs / 1e12).toFixed(digits ?? 2)}T`
  if (abs >= 1e9) return `${sign}${prefix}${(abs / 1e9).toFixed(digits ?? 1)}B`
  if (abs >= 1e6) return `${sign}${prefix}${(abs / 1e6).toFixed(digits ?? 0)}M`
  return `${sign}${prefix}${abs.toLocaleString('en-US', { maximumFractionDigits: 2 })}`
}

export function formatUnit(value, unit, currency) {
  if (value === null || value === undefined) return '—'
  if (unit === 'ratio') return formatPct(value)
  if (unit === 'days') return `${Math.round(value)} d`
  if (unit === 'currency_per_share') return `${value < 0 ? '−' : ''}${currencyPrefix(currency)}${Math.abs(value).toFixed(2)}`
  if (unit === 'shares') return `${(value / 1e6).toLocaleString('en-US', { maximumFractionDigits: 0 })}M shares`
  return formatMoney(value, currency)
}

export function periodLabel(fiscalYear, fiscalPeriod) {
  if (!fiscalYear) return ''
  const year = `FY${String(fiscalYear).slice(-2)}`
  return fiscalPeriod === 'FY' ? `FY${fiscalYear}` : `${fiscalPeriod} ${year}`
}
