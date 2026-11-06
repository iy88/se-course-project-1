/** 图片上传错误提示：优先展示服务端/本地校验的具体原因，避免统一下沉成“上传失败”。 */

const GENERIC_DEFAULTS = [/network error/i, /timeout of/i, /status code/i]

/** 返回可直接展示给用户的失败原因；无法识别时用调用方指定的兜底文案。 */
export function uploadErrorMessage(error, fallback = '上传失败，请重试') {
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string' && detail.trim()) return detail.trim()

  const message = typeof error?.message === 'string' ? error.message.trim() : ''
  if (message && !GENERIC_DEFAULTS.some((pattern) => pattern.test(message))) return message

  return fallback
}
