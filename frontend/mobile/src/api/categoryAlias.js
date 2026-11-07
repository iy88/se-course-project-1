/** Category alias display: the primary name and aliases refer to the same category tag; aliases are not separately checkable tags (US-13-AC-07, D-45). */

/** Alias hint for a category dropdown item; aliases do not count as separate tags, and selecting the item filters by the same category. */
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
