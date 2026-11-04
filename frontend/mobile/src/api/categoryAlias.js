/** 分类别名展示：主名与别名指向同一分类标签，不把别名当作可重复勾选的独立标签（US-13-AC-07、D-45）。 */

/** 分类下拉项的别名说明；别名不能单独计为一个标签，选择该项即按同一分类筛选。 */
export function categoryAliasHint(category) {
  const aliases = Array.isArray(category?.aliases)
    ? category.aliases
        .filter((alias) => alias !== null && alias !== undefined)
        .map((alias) => String(alias).trim())
        .filter(Boolean)
    : []
  if (!aliases.length) return ''
  return `（${aliases.join('、')}，同属本分类）`
}
