// Distinct chart series against the warm paper surface. Checked with the dataviz palette validator: every pair stays
// distinguishable under common color-vision deficiencies (adjacent CVD delta E >= 8) and none reads gray.
export const SERIES = {
  blue: '#355e99',
  orange: '#c8702a',
  aqua: '#009688',
}

export const CHART_CHROME = {
  grid: '#ebe7df',
  axis: '#d2cdc4',
  tick: '#6c6963',
  label: '#575650',
  surface: '#fffefa',
}

export const AXIS_TICK = { fill: CHART_CHROME.tick, fontSize: 11 }

// Status colors carry meaning (good / bad) and always ship with an icon and a sign, never color alone.
export const STATUS = {
  good: '#287252',
  warning: '#946819',
  critical: '#a43e39',
}
