/**
 * 交易处置上下文的纯状态规则：展示与动作只使用“当前交易+当前事项”的最新成功加载结果。
 * 仅用于前端预检，最终权限由服务端校验。
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

/** 输入或事项变化时使旧内容与旧动作立即失效，并让在途响应全部过期。 */
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

/** 只有已加载且与当前输入完全一致的交易可以展示或执行动作。 */
export function canUseLoadedTrade(session, context) {
  if (!session || session.loading || session.actionBusy) return false
  const ctx = normalizeTradeContext(context.tradeId, context.caseId)
  if (!ctx.tradeId || !ctx.caseId) return false
  if (!session.loaded || !isSameTradeContext(session.loaded, ctx)) return false
  return Number(session.loaded.trade?.id) === ctx.tradeId
}

/** 动作开始时锁定目标上下文；处理中再次调用返回 null，用于阻止重复提交。 */
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
