/**
 * Pure realtime cursor rules shared by the mobile client and Node tests.
 * Business callbacks are applied only after an event is classified as the next
 * contiguous user_seq; duplicates are ACKed again, gaps trigger a replay.
 */

export const MAX_SEEN_EVENTS = 512

export function createState() {
  return { lastSeq: 0, seen: new Set() }
}

export function resetState(state) {
  state.lastSeq = 0
  state.seen.clear()
}

function validSeq(value) {
  return Number.isSafeInteger(value) && value > 0
}

/**
 * @returns {{kind:'apply'|'duplicate'|'gap'|'resync'|'ignore', seq?:number, expected?:number}}
 */
export function classifyEvent(state, frame) {
  if (!frame || typeof frame !== 'object') return { kind: 'ignore' }
  if (frame.type === 'resync_required') return { kind: 'resync' }
  if (frame.type !== 'event') return { kind: 'ignore' }
  const seq = Number(frame.user_seq)
  if (!validSeq(seq) || typeof frame.event_id !== 'string' || !frame.event_id) {
    return { kind: 'ignore' }
  }
  if (state.seen.has(frame.event_id) || seq <= state.lastSeq) {
    return { kind: 'duplicate', seq }
  }
  if (state.lastSeq > 0 && seq !== state.lastSeq + 1) {
    return { kind: 'gap', seq, expected: state.lastSeq + 1 }
  }
  if (state.lastSeq === 0 && seq > 1) {
    return { kind: 'gap', seq, expected: 1 }
  }
  return { kind: 'apply', seq }
}

/** Commit only after the event's business payload has been applied. */
export function commitEvent(state, frame) {
  const seq = Number(frame.user_seq)
  if (!validSeq(seq) || seq <= state.lastSeq) return state.lastSeq
  state.lastSeq = seq
  state.seen.add(frame.event_id)
  while (state.seen.size > MAX_SEEN_EVENTS) {
    const first = state.seen.values().next().value
    state.seen.delete(first)
  }
  return state.lastSeq
}

/** Await the business handler; commit only after it resolves successfully. */
export async function applySequenced(state, frame, handler) {
  const result = classifyEvent(state, frame)
  if (result.kind === 'apply') {
    await handler(frame.payload || { type: frame.event_type })
    commitEvent(state, frame)
  }
  return result
}

export function ackFrame(seq, eventId) {
  return { type: 'ack', user_seq: seq, event_id: eventId }
}

export function needsResync(since, lowSeq, highSeq) {
  return since > highSeq || since < lowSeq - 1
}

/** 0.5–30 s exponential backoff with jitter; never returns 0. */
export function reconnectDelay(attempt, random = Math.random) {
  const base = Math.min(30000, 500 * 2 ** Math.min(Math.max(attempt, 0), 6))
  const jitter = 0.75 + Math.max(0, Math.min(1, random())) * 0.5
  return Math.min(30000, Math.max(500, Math.round(base * jitter)))
}

export function shouldStopForAuth(code) {
  return code === 4401 || code === 4403
}
