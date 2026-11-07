/** Seller's pending tag applications in product editing (contracts ROUND2 13 / R11). */

import { isCategorySelectable } from '../../../shared/categorySelection.mjs'

/** Disabled tags cannot be used for new publishes or new associations; when editing an existing product only previously associated disabled tags are retained (4.16, US-13-AC-04).
 * The rule is shared with admin category correction via `shared/categorySelection.mjs`, re-exported here to keep existing import paths. */
export { isCategorySelectable }

/** Use only the current user's pending applications returned by the server; when other viewers get an empty array, never infer or fabricate IDs. */
export function pendingTagApplications(product) {
  const applications = product?.pending_tag_applications
  if (!Array.isArray(applications)) return []
  return applications.filter(
    (application) =>
      application &&
      Number.isInteger(Number(application.id)) &&
      (application.status === undefined || application.status === 'pending') &&
      typeof application.requested_name === 'string' &&
      application.requested_name.trim(),
  )
}

/** Determine resubmission only from the server's can_resubmit; withdrawing a pending tag application must not become a republish or create a new draft. */
export function resolveResubmitMode(product) {
  if (!product) return false
  if (product.can_resubmit === true) return true
  return product.can_resubmit === undefined && product.status === 'rejected'
}

/** Filter withdrawal selections that still belong to current pending applications and report stale selections separately, avoiding silent submission of old IDs. */
export function withdrawalSelection(selectedIds, applications) {
  const allowed = new Set((applications || []).map((application) => Number(application.id)))
  const ids = [...new Set((selectedIds || []).map((id) => Number(id)).filter(Number.isInteger))]
  return {
    ids: ids.filter((id) => allowed.has(id)),
    stale: ids.filter((id) => !allowed.has(id)),
  }
}
