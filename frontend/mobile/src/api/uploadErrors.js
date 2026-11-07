/** Image upload error messages: prefer the specific reason from the server/local validation instead of collapsing everything into "upload failed". */

const GENERIC_DEFAULTS = [/network error/i, /timeout of/i, /status code/i]

/** Return a failure reason suitable for direct display; if unrecognized, use the caller-provided fallback copy. */
export function uploadErrorMessage(error, fallback = '上传失败，请重试') {
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string' && detail.trim()) return detail.trim()

  const message = typeof error?.message === 'string' ? error.message.trim() : ''
  if (message && !GENERIC_DEFAULTS.some((pattern) => pattern.test(message))) return message

  return fallback
}
