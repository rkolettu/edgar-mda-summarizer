import test from 'node:test'
import assert from 'node:assert/strict'
import { formatChange } from './changeFormatting.js'

const percent = (value) => `${(value * 100).toFixed(1)}%`

test('day metrics retain day units without percentage scaling', () => {
  assert.equal(formatChange(58.356, 'days', percent), '+58 days')
})

test('ratio metrics remain percentage-point changes', () => {
  assert.equal(formatChange(0.058356, 'ratio', percent), '+5.8 pts')
  assert.equal(formatChange(-0.08, 'points', percent), '-8.0 pts')
})
