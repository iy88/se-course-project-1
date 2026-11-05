// Route changes, retries and unmount invalidate older responses, including permission failures.
export function createEditHistoryLoader(fetchRecords, update) {
  let generation = 0
  async function load(productId) {
    const current = ++generation
    update({ records: [], loading: true, loaded: false, error: '' })
    try {
      const records = await fetchRecords(productId)
      if (current !== generation) return
      update({ records, loading: false, loaded: true, error: '' })
    } catch (err) {
      if (current !== generation) return
      const status = err?.response?.status
      const error = status === 403 || status === 404
        ? '商品不存在或您无权查看其编辑历史。'
        : '编辑历史加载失败，请稍后重试。'
      update({ records: [], loading: false, loaded: true, error })
    }
  }
  return { load, invalidate() { generation++ } }
}
