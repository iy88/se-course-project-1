/**
 * 分类可选择性（4.16、US-13-AC-04）。
 *
 * - 停用分类不可用于新发布或新增关联；
 * - 已有商品编辑/分类纠正时，仅保留原先已关联的停用分类，并仍可取消该关联。
 *
 * 移动端发布/编辑与管理端分类纠正共用本模块，避免两处规则漂移。
 */

/** 判断某分类在当前上下文是否可选；initialCategoryIds 为对象当前已关联的分类 ID。 */
export function isCategorySelectable(category, initialCategoryIds = []) {
  if (!category) return false
  if (category.status !== 'disabled') return true
  const initial = new Set((initialCategoryIds || []).map((id) => Number(id)))
  return initial.has(Number(category.id))
}

/** 停用分类仍可展示时标注状态，避免被误认为可新增。 */
export function categoryOptionLabel(category) {
  if (!category) return ''
  return category.status === 'disabled' ? `${category.name}（已停用）` : category.name
}

/** 管理端纠正的可选项：启用分类 + 当前商品已关联的停用分类。 */
export function selectableCategoryOptions(categories, initialCategoryIds = []) {
  return (categories || []).filter((category) => isCategorySelectable(category, initialCategoryIds))
}
