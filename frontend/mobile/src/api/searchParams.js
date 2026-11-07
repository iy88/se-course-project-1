/** Product search parameters (D-45 / contracts ROUND2 16): arrays use repeat-key so FastAPI list[int] never receives the [] form. */

export function normalizeNameFilters(value) {
  if (Array.isArray(value)) {
    return value.map((item) => String(item).trim()).filter(Boolean)
  }
  if (value === null || value === undefined) return []
  const name = String(value).trim()
  return name ? [name] : []
}

export function buildProductSearchParams({
  page = 1,
  pageSize = 20,
  keyword = '',
  categoryIds = [],
  categoryNames = [],
  priceMin = null,
  priceMax = null,
} = {}) {
  const params = new URLSearchParams()
  params.set('page', String(page))
  params.set('page_size', String(pageSize))
  if (keyword) params.set('keyword', keyword)
  for (const id of categoryIds || []) {
    if (id === null || id === undefined || id === '') continue
    params.append('category_ids', String(id))
  }
  // Unknown/removed names are still sent to the server and treated as no match; do not silently drop them on the frontend as "all products".
  for (const name of categoryNames || []) {
    const trimmed = String(name).trim()
    if (trimmed) params.append('category_names', trimmed)
  }
  if (priceMin !== null && priceMin !== undefined && priceMin !== '') {
    params.set('price_min_cents', String(priceMin))
  }
  if (priceMax !== null && priceMax !== undefined && priceMax !== '') {
    params.set('price_max_cents', String(priceMax))
  }
  return params
}
