// Each open form owns its cache; a failed submission keeps successful uploads.
export function createEvidenceUploads(upload) {
  const keys = new Map()
  return {
    retain(items) {
      const selected = new Set(items.map((item) => item?.file).filter(Boolean))
      for (const file of keys.keys()) if (!selected.has(file)) keys.delete(file)
    },
    clear() { keys.clear() },
    async upload(items) {
      this.retain(items)
      const result = []
      for (const item of items) {
        const file = item?.file
        if (!file) continue
        if (!keys.has(file)) keys.set(file, await upload(file, 'report'))
        result.push(keys.get(file))
      }
      return result
    },
  }
}
