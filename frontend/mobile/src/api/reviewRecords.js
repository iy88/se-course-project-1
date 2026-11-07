/**
 * Product review-record request controller: a new route/retry request always supersedes the old one.
 * Old responses must not overwrite records for a new product, and must not write page state after unmount.
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
