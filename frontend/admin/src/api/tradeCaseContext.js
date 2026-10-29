/** 交易处置事项上下文的前端预检规则；最终权限由服务端校验。 */

const USABLE_CASE_STATUSES = new Set(['processing', 'disposed'])
const TRADE_CONTEXT_EXCLUDED_TYPES = new Set(['product_review'])

/** 商品审核事项不能作为后续私人交易访问、冻结或状态调整的上下文。 */
export function isTradeContextCaseType(caseRow) {
  return Boolean(caseRow) && !TRADE_CONTEXT_EXCLUDED_TYPES.has(caseRow.case_type)
}

/** 只有本人认领的处理中/已处置事项可用于交易上下文；已处置不表示后续合法解冻/调整一定不可用。 */
export function isOwnedUsableCase(caseRow, adminId) {
  if (!caseRow || !adminId) return false
  if (!isTradeContextCaseType(caseRow)) return false
  return Number(caseRow.claimed_by_id) === Number(adminId) && USABLE_CASE_STATUSES.has(caseRow.status)
}

export function ownedUsableCases(caseRows, adminId) {
  return (caseRows || [])
    .filter((caseRow) => isOwnedUsableCase(caseRow, adminId))
    .sort((a, b) => {
      if (a.status !== b.status) return a.status === 'processing' ? -1 : 1
      return Number(b.id) - Number(a.id)
    })
}

/** 事项须至少带有一个业务关联对象，避免“任意本人事项”成为通用交易许可。 */
export function caseHasContext(caseRow) {
  if (!caseRow) return false
  return Boolean(caseRow.trade_id || caseRow.product_id || caseRow.report_id || caseRow.subject_user_id)
}

/**
 * 事项是否可能作为该交易的上下文：
 * - 商品审核事项不能作为私人交易上下文，即使与本交易商品相同；
 * - 直接关联交易时必须一致，不能因相同商品等间接关系绕过；
 * - 无直接交易关联时，举报/账户关联可交由服务端进一步核验。
 */
export function caseCanContextTrade(caseRow, tradeId) {
  if (!caseHasContext(caseRow) || !tradeId) return false
  if (!isTradeContextCaseType(caseRow)) return false
  if (caseRow.trade_id == null) return true
  return Number(caseRow.trade_id) === Number(tradeId)
}

export function isDirectTradeMismatch(caseRow, tradeId) {
  return Boolean(
    caseRow &&
      caseRow.trade_id != null &&
      tradeId &&
      Number(caseRow.trade_id) !== Number(tradeId),
  )
}
