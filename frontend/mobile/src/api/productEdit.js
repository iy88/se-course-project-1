/** 商品编辑中的卖方待审核标签申请（contracts ROUND2 13 / R11）。 */

/** 仅采用服务端返回的本人待审核申请；其他浏览者返回空数组时不得自行推测或补造 ID。 */
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

/** 只依据服务端 can_resubmit 判断重提；撤回待审核标签申请不能变成重新发布或新造草稿。 */
export function resolveResubmitMode(product) {
  if (!product) return false
  if (product.can_resubmit === true) return true
  return product.can_resubmit === undefined && product.status === 'rejected'
}

/** 过滤出仍属于当前待审核申请的撤回选择，并单独报告已失效选择，避免静默提交旧 ID。 */
export function withdrawalSelection(selectedIds, applications) {
  const allowed = new Set((applications || []).map((application) => Number(application.id)))
  const ids = [...new Set((selectedIds || []).map((id) => Number(id)).filter(Number.isInteger))]
  return {
    ids: ids.filter((id) => allowed.has(id)),
    stale: ids.filter((id) => !allowed.has(id)),
  }
}
