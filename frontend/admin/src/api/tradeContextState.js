/**
 * Pure state rules for trade-disposition context: display and actions use only
 * the latest successful load for the current trade plus current case.
 * Frontend preflight only; final authorization is validated by the server.
 */

export function normalizeTradeContext(tradeId, caseId) {
  const t = Number(tradeId)
  const c = Number(caseId)
  return {
    tradeId: Number.isFinite(t) && t > 0 ? t : null,
    caseId: Number.isFinite(c) && c > 0 ? c : null,
  }
}

export function isSameTradeContext(a, b) {
  return Boolean(
    a &&
      b &&
      a.tradeId != null &&
      b.tradeId != null &&
      Number(a.tradeId) === Number(b.tradeId) &&
      a.caseId != null &&
      b.caseId != null &&
      Number(a.caseId) === Number(b.caseId),
  )
}

export function createTradeSession() {
  return {
    seq: 0,
    loading: false,
    actionBusy: false,
    loaded: null,
    pending: null,
    actionTarget: null,
  }
}

/** Invalidate old content and actions immediately when input or case changes, and expire all in-flight responses. */
export function invalidateTradeSession(session) {
  return {
    seq: session.seq + 1,
    loading: false,
    actionBusy: false,
    loaded: null,
    pending: null,
    actionTarget: null,
  }
}

export function beginTradeLoad(session, context) {
  if (session.actionBusy) return session
  const ctx = normalizeTradeContext(context.tradeId, context.caseId)
  if (!ctx.tradeId || !ctx.caseId) return session
  const seq = session.seq + 1
  return {
    ...session,
    seq,
    loading: true,
    loaded: null,
    pending: { seq, ...ctx },
  }
}

export function finishTradeLoad(session, response) {
  const ctx = normalizeTradeContext(response.context.tradeId, response.context.caseId)
  if (!session.pending || Number(response.seq) !== Number(session.seq)) {
    return { session, accepted: false, reason: 'stale' }
  }
  if (!isSameTradeContext(session.pending, ctx)) {
    return { session, accepted: false, reason: 'context' }
  }
  if (!response.trade || Number(response.trade.id) !== ctx.tradeId) {
    return {
      session: failTradeLoad(session, { seq: response.seq, context: ctx }),
      accepted: false,
      reason: 'trade-id',
    }
  }
  return {
    session: {
      ...session,
      loading: false,
      pending: null,
      loaded: { ...ctx, trade: response.trade },
    },
    accepted: true,
  }
}

export function failTradeLoad(session, response) {
  const ctx = normalizeTradeContext(response.context.tradeId, response.context.caseId)
  if (!session.pending || Number(response.seq) !== Number(session.seq)) return session
  if (!isSameTradeContext(session.pending, ctx)) return session
  return { ...session, loading: false, pending: null, loaded: null }
}

/** Only a loaded trade that exactly matches the current input may be displayed or acted on. */
export function canUseLoadedTrade(session, context) {
  if (!session || session.loading || session.actionBusy) return false
  const ctx = normalizeTradeContext(context.tradeId, context.caseId)
  if (!ctx.tradeId || !ctx.caseId) return false
  if (!session.loaded || !isSameTradeContext(session.loaded, ctx)) return false
  return Number(session.loaded.trade?.id) === ctx.tradeId
}

/** Lock the target context when an action starts; returns null if called again while busy to prevent duplicate submission. */
export function beginTradeAction(session, context) {
  if (!canUseLoadedTrade(session, context)) return null
  const ctx = normalizeTradeContext(context.tradeId, context.caseId)
  return {
    ...session,
    actionBusy: true,
    actionTarget: { ...ctx, tradeId: Number(session.loaded.trade.id) },
  }
}

export function endTradeAction(session, target) {
  if (!session.actionTarget || !isSameTradeContext(session.actionTarget, target)) return session
  return { ...session, actionBusy: false, actionTarget: null }
}
