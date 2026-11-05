export function productTradesLink(productId) {
  return { path: '/me/trades', query: { role: 'seller', product_id: String(productId) } }
}

export function parseTradeFilters(query) {
  const role = ['all', 'buyer', 'seller'].includes(query.role) ? query.role : 'all'
  const params = { role }
  if (query.product_id !== undefined) {
    const value = query.product_id
    const id = typeof value === 'string' && /^[1-9]\d*$/.test(value) ? Number(value) : NaN
    if (!Number.isSafeInteger(id)) return { params, error: '商品筛选参数无效，请清除商品筛选后重试。' }
    params.product_id = id
  }
  return { params, error: '' }
}

export function createMyTradesLoader(fetchTrades, update) {
  let generation = 0
  async function load(query) {
    const current = ++generation
    const { params, error } = parseTradeFilters(query)
    update({ trades: [], loaded: false, loading: !error, error })
    if (error) return
    try {
      const trades = await fetchTrades(params)
      if (current !== generation) return
      update({ trades, loaded: true, loading: false, error: '' })
    } catch {
      if (current !== generation) return
      update({ trades: [], loaded: true, loading: false, error: '交易列表加载失败，请稍后重试。' })
    }
  }
  return { load, invalidate() { generation++ } }
}
