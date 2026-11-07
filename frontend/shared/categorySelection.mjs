/**
 * Category selectability (4.16, US-13-AC-04).
 *
 * - Disabled categories cannot be used for new publishes or new associations;
 * - When editing an existing product/correcting categories, only previously
 *   associated disabled categories are retained, and that association can
 *   still be removed.
 *
 * Mobile publishing/editing and admin category correction share this module to
 * keep the rule from drifting between the two.
 */

/** Whether a category is selectable in the current context; initialCategoryIds are the IDs currently associated with the object. */
export function isCategorySelectable(category, initialCategoryIds = []) {
  if (!category) return false
  if (category.status !== 'disabled') return true
  const initial = new Set((initialCategoryIds || []).map((id) => Number(id)))
  return initial.has(Number(category.id))
}

/** Mark the status when a disabled category is still displayed, so it is not mistaken for one that can be added. */
export function categoryOptionLabel(category) {
  if (!category) return ''
  return category.status === 'disabled' ? `${category.name}（已停用）` : category.name
}

/** Options for admin correction: enabled categories plus disabled categories already associated with the current product. */
export function selectableCategoryOptions(categories, initialCategoryIds = []) {
  return (categories || []).filter((category) => isCategorySelectable(category, initialCategoryIds))
}
