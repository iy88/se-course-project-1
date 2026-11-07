/** Frontend preflight rules for trade-disposition case context; final authorization is validated by the server. */

const USABLE_CASE_STATUSES = new Set(['processing', 'disposed'])
const TRADE_CONTEXT_EXCLUDED_TYPES = new Set(['product_review'])

/** Product-review cases cannot serve as context for later private-trade access, freezing, or status changes. */
export function isTradeContextCaseType(caseRow) {
  return Boolean(caseRow) && !TRADE_CONTEXT_EXCLUDED_TYPES.has(caseRow.case_type)
}

/** Only processing/disposed cases claimed by the current admin may serve as trade context; disposed does not mean later legitimate unfreezing/adjustments are necessarily unavailable. */
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

/** A case must have at least one business-linked object so that "any case owned by me" cannot become a blanket trade permit. */
export function caseHasContext(caseRow) {
  if (!caseRow) return false
  return Boolean(caseRow.trade_id || caseRow.product_id || caseRow.report_id || caseRow.subject_user_id)
}

/**
 * Whether a case could serve as context for this trade:
 * - Product-review cases cannot serve as private-trade context, even when they
 *   involve the same product as the trade;
 * - A directly linked trade must match, and indirect relations such as the same
 *   product cannot bypass this check;
 * - Without a direct trade link, report/account associations may be further
 *   verified by the server.
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
