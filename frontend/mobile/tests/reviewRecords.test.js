import { test } from 'node:test'
import assert from 'node:assert/strict'
import { reviewResultLabels, reviewResultTone } from '../src/api/labels.js'

test('review result labels cover every server result', () => {
  assert.equal(reviewResultLabels.pending, '待审核')
  assert.equal(reviewResultLabels.approved, '审核通过')
  assert.equal(reviewResultLabels.rejected, '审核未通过')
  assert.equal(reviewResultLabels.withdrawn, '已撤回')
})

test('review result tone maps known results and keeps unknown results neutral', () => {
  assert.equal(reviewResultTone('approved'), 'pill--ok')
  assert.equal(reviewResultTone('rejected'), 'pill--danger')
  assert.equal(reviewResultTone('pending'), 'pill--warn')
  assert.equal(reviewResultTone('withdrawn'), '')
  assert.equal(reviewResultTone('unknown'), '')
  assert.equal(reviewResultTone(undefined), '')
})
