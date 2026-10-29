import test from 'node:test'
import assert from 'node:assert/strict'

import { fmtTime as adminFmtTime } from '../admin/src/api/time.js'
import { fmtTime as mobileFmtTime } from '../mobile/src/api/labels.js'

const implementations = [
  ['admin/src/api/time.js', adminFmtTime],
  ['mobile/src/api/labels.js', mobileFmtTime],
]

const formatCases = [
  {
    name: 'naive UTC ISO datetime is interpreted as UTC',
    input: '2026-10-29T04:40:29',
    expected: '2026/10/29 12:40:29',
  },
  {
    name: 'naive UTC with space separator is interpreted as UTC',
    input: '2026-10-29 04:40:29',
    expected: '2026/10/29 12:40:29',
  },
  {
    name: 'explicit Z keeps its UTC instant',
    input: '2026-10-29T04:40:29Z',
    expected: '2026/10/29 12:40:29',
  },
  {
    name: 'explicit +08:00 already at Beijing time is not shifted twice',
    input: '2026-10-29T12:40:29+08:00',
    expected: '2026/10/29 12:40:29',
  },
  {
    name: 'negative offset is honored',
    input: '2026-10-29T04:40:29-05:00',
    expected: '2026/10/29 17:40:29',
  },
  {
    name: 'UTC cross-day boundary rolls to next Beijing calendar day',
    input: '2026-10-29T20:30:00',
    expected: '2026/10/30 04:30:00',
  },
  {
    name: 'fractional seconds are accepted for the displayed second',
    input: '2026-10-29T04:40:29.987654',
    expected: '2026/10/29 12:40:29',
  },
]

for (const [implName, fmtTime] of implementations) {
  test(`${implName}: formats datetimes in Asia/Shanghai`, async (t) => {
    for (const item of formatCases) {
      await t.test(item.name, () => {
        assert.equal(fmtTime(item.input), item.expected)
      })
    }
  })

  test(`${implName}: missing and invalid values return an empty string`, async (t) => {
    const invalidValues = [
      null,
      undefined,
      '',
      '   ',
      'not-a-date',
      '2026-13-01T00:00:00',
      '2026-02-30T00:00:00',
      '2026-10-29T25:00:00',
      '2026-10-29T04:40:29+25:00',
      '2026-10-29',
    ]
    for (const value of invalidValues) {
      await t.test(`invalid: ${JSON.stringify(value)}`, () => {
        assert.equal(fmtTime(value), '')
      })
    }
  })
}

test('display regression: stored 04:40:29 UTC shows 12:40:29 in Beijing', () => {
  for (const [implName, fmtTime] of implementations) {
    assert.equal(fmtTime('2026-10-29T04:40:29'), '2026/10/29 12:40:29', implName)
  }
})

test('display regression: explicit +08:00 12:40:29 stays 12:40:29', () => {
  for (const [implName, fmtTime] of implementations) {
    assert.equal(fmtTime('2026-10-29T12:40:29+08:00'), '2026/10/29 12:40:29', implName)
  }
})
