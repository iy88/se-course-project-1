import test from 'node:test'
import assert from 'node:assert/strict'

import {
  ackFrame,
  applySequenced,
  classifyEvent,
  commitEvent,
  createState,
  needsResync,
  reconnectDelay,
  resetState,
} from '../src/api/realtimeProtocol.mjs'

function event(seq, id = `e-${seq}`) {
  return { type: 'event', user_seq: seq, event_id: id, payload: { type: 'message' } }
}

test('applies contiguous events once and dedupes repeated event_id', () => {
  const state = createState()
  assert.deepEqual(classifyEvent(state, event(1)), { kind: 'apply', seq: 1 })
  commitEvent(state, event(1))
  assert.equal(state.lastSeq, 1)
  assert.deepEqual(classifyEvent(state, event(1)), { kind: 'duplicate', seq: 1 })
  assert.deepEqual(classifyEvent(state, event(2)), { kind: 'apply', seq: 2 })
})

test('detects a gap without advancing the cursor', () => {
  const state = createState()
  commitEvent(state, event(3))
  assert.deepEqual(classifyEvent(state, event(5)), { kind: 'gap', seq: 5, expected: 4 })
  assert.equal(state.lastSeq, 3)
  assert.deepEqual(classifyEvent(state, event(4)), { kind: 'apply', seq: 4 })
})

test('first event must be sequence 1 unless replay establishes otherwise', () => {
  const state = createState()
  assert.deepEqual(classifyEvent(state, event(7)), { kind: 'gap', seq: 7, expected: 1 })
})

test('resync frames and malformed frames are classified safely', () => {
  const state = createState()
  assert.deepEqual(classifyEvent(state, { type: 'resync_required', high_seq: 9 }), { kind: 'resync' })
  assert.deepEqual(classifyEvent(state, null), { kind: 'ignore' })
  assert.deepEqual(classifyEvent(state, { type: 'event', user_seq: 0 }), { kind: 'ignore' })
  assert.deepEqual(classifyEvent(state, { type: 'event', user_seq: 1 }), { kind: 'ignore' })
})

test('reset clears the cursor for account switches', () => {
  const state = createState()
  commitEvent(state, event(1))
  resetState(state)
  assert.equal(state.lastSeq, 0)
  assert.equal(state.seen.size, 0)
})

test('ACK contains the applied sequence and event id', () => {
  assert.deepEqual(ackFrame(4, 'abc'), { type: 'ack', user_seq: 4, event_id: 'abc' })
})

test('retention watermark requires resync only outside the retained range', () => {
  assert.equal(needsResync(10, 5, 20), false)
  assert.equal(needsResync(3, 5, 20), true)
  assert.equal(needsResync(21, 5, 20), true)
  assert.equal(needsResync(4, 5, 20), false) // low_seq is inclusive
})

test('reconnect jitter stays in the bounded 0.5-30s range', () => {
  for (let attempt = 0; attempt < 20; attempt += 1) {
    for (const random of [0, 0.5, 1]) {
      const delay = reconnectDelay(attempt, () => random)
      assert.ok(delay >= 500, `attempt ${attempt} delay ${delay}`)
      assert.ok(delay <= 30000, `attempt ${attempt} delay ${delay}`)
    }
  }
})

test('awaits a delayed async handler before committing the cursor', async () => {
  const state = createState()
  let finished = false
  const pending = applySequenced(state, event(1), async () => {
    await new Promise((resolve) => setTimeout(resolve, 10))
    finished = true
  })
  assert.equal(state.lastSeq, 0)
  await pending
  assert.equal(finished, true)
  assert.equal(state.lastSeq, 1)
})

test('rejected handler does not advance the cursor or ACK the event', async () => {
  const state = createState()
  await assert.rejects(
    applySequenced(state, event(1), async () => { throw new Error('snapshot failed') }),
    /snapshot failed/,
  )
  assert.equal(state.lastSeq, 0)
  assert.equal(state.seen.size, 0)
})
