import test from 'node:test'
import assert from 'node:assert/strict'
import { usefulBreakdowns } from './business.js'

const view = (items) => ({ annual: { label: 'FY2025', items } })

test('a single reportable segment does not crowd out useful product and geography data', () => {
  const result = usefulBreakdowns([
    { family: 'segment', ...view([{ metric: 'revenue', label: 'Reportable segment' }]) },
    { family: 'product', ...view([{ metric: 'revenue', label: 'Product A' }, { metric: 'revenue', label: 'Product B' }]) },
    { family: 'geography', ...view([{ metric: 'revenue', label: 'United States' }]) },
  ])
  assert.deepEqual(result.map((item) => item.family), ['product', 'geography'])
})

test('multi-segment companies retain their segment mix', () => {
  const result = usefulBreakdowns([{ family: 'segment', ...view([
    { metric: 'revenue', label: 'Compute' }, { metric: 'revenue', label: 'Networking' },
  ]) }])
  assert.equal(result.length, 1)
})
