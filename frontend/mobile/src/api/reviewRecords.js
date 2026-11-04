/**
 * 商品审核记录请求控制器：新路由/重试请求总是取代旧请求。
 * 旧响应不得覆盖新商品的记录；卸载后也不能继续写入页面状态。
 */
export function createReviewRecordsLoader(fetchRecords, updateState) {
  let requestId = 0

  async function load(productId) {
    const current = ++requestId
    updateState({ records: [], loaded: false, loading: true, error: '' })
    try {
      const data = await fetchRecords(productId)
      if (current !== requestId) return
      updateState({
        records: Array.isArray(data) ? data : [],
        loaded: true,
        loading: false,
        error: '',
      })
    } catch {
      if (current !== requestId) return
      updateState({
        records: [],
        loaded: true,
        loading: false,
        error: '审核记录加载失败，请稍后重试。',
      })
    }
  }

  function invalidate() {
    requestId++
  }

  return { load, invalidate }
}
