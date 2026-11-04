import { test } from 'node:test'
import assert from 'node:assert/strict'
import { reviewResultLabels, reviewResultTone } from '../src/api/labels.js'
import { createReviewRecordsLoader } from '../src/api/reviewRecords.js'

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

function deferred() {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

test('switching products displays only the newest response, even if the older request resolves later', async () => {
  const old = deferred()
  const latest = deferred()
  const calls = []
  const state = {}
  const loader = createReviewRecordsLoader(
    (id) => { calls.push(id); return id === '5' ? old.promise : latest.promise },
    (patch) => Object.assign(state, patch),
  )
  const oldLoad = loader.load('5')
  const newLoad = loader.load('6')
  assert.deepEqual(calls, ['5', '6'])
  assert.equal(state.loading, true)
  assert.deepEqual(state.records, [])
  latest.resolve([{ id: 22, result: 'approved' }])
  await newLoad
  old.resolve([{ id: 11, result: 'rejected' }])
  await oldLoad
  assert.deepEqual(state.records.map((r) => r.id), [22])
  assert.equal(state.loading, false)
  assert.equal(state.error, '')
})

test('an older failure cannot overwrite newer success; retry while loading uses newest request', async () => {
  const old = deferred()
  const latest = deferred()
  let count = 0
  const state = {}
  const loader = createReviewRecordsLoader(
    () => ++count === 1 ? old.promise : latest.promise,
    (patch) => Object.assign(state, patch),
  )
  const first = loader.load('5')
  const retry = loader.load('5')
  latest.resolve([])
  await retry
  old.reject(new Error('stale failure'))
  await first
  assert.deepEqual(state.records, [])
  assert.equal(state.loaded, true)
  assert.equal(state.error, '')
  assert.equal(state.loading, false)
})

test('latest failure renders an error and invalidation prevents late updates after unmount', async () => {
  const fail = deferred()
  const state = {}
  const loader = createReviewRecordsLoader(() => fail.promise, (patch) => Object.assign(state, patch))
  const loading = loader.load('5')
  fail.reject(new Error('network'))
  await loading
  assert.match(state.error, /加载失败/)
  assert.equal(state.loading, false)

  const late = deferred()
  const updates = []
  const unmounted = createReviewRecordsLoader(() => late.promise, (patch) => updates.push(patch))
  const pending = unmounted.load('7')
  const before = updates.length
  unmounted.invalidate()
  late.resolve([{ id: 33 }])
  await pending
  assert.equal(updates.length, before)
})
