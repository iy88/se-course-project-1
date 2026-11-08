import http from './http'

const MAX_IMAGE_BYTES = 100 * 1024 * 1024
const IMAGE_TYPES = new Set(['image/jpeg', 'image/png', 'image/webp', 'image/gif'])
const EXTENSION_TYPES = new Map([
  ['jpg', 'image/jpeg'],
  ['jpeg', 'image/jpeg'],
  ['png', 'image/png'],
  ['webp', 'image/webp'],
  ['gif', 'image/gif'],
])

function contentTypeFor(file) {
  const declared = String(file.type || '').toLowerCase()
  if (declared) return declared
  const extension = String(file.name || '').split('.').pop()?.toLowerCase()
  return EXTENSION_TYPES.get(extension) || ''
}

async function sha256Hex(file) {
  const bytes = await file.arrayBuffer()
  const digest = await crypto.subtle.digest('SHA-256', bytes)
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('')
}

function resolveUploadUrl(uploadUrl) {
  const apiBase = import.meta.env.VITE_API_BASE_URL || '/api/v1'
  const apiRoot = new URL(apiBase.endsWith('/') ? apiBase : `${apiBase}/`, window.location.origin)
  return new URL(uploadUrl, apiRoot).toString()
}

/** Validate before adding a file to the picker or starting an upload. */
export function validateImageFile(file) {
  if (!(file instanceof File)) throw new Error('请选择有效图片')
  if (file.size <= 0) throw new Error('图片不能为空')
  if (file.size > MAX_IMAGE_BYTES) throw new Error('图片不能超过 100 MiB')

  const contentType = contentTypeFor(file)
  if (!IMAGE_TYPES.has(contentType)) throw new Error('仅支持 JPG、PNG、WebP 或 GIF 图片')
  return contentType
}

/** Obtain a short-lived upload lease, upload bytes directly, then commit the verified object. */
export async function uploadImage(file, namespace = 'product') {
  const contentType = validateImageFile(file)
  const sha256 = await sha256Hex(file)
  const lease = await http.post('/files/upload-leases', {
    namespace,
    filename: file.name,
    content_type: contentType,
    size_bytes: file.size,
    sha256,
  })

  if (!lease?.lease_id || !lease?.upload?.url || !lease?.upload?.method) {
    throw new Error('服务器返回的上传凭据无效')
  }

  const headers = new Headers()
  for (const [name, value] of Object.entries(lease.upload.headers || {})) {
    // Content-Length is controlled by the browser and cannot be set by page JavaScript.
    if (name.toLowerCase() !== 'content-length') headers.set(name, value)
  }

  const response = await fetch(resolveUploadUrl(lease.upload.url), {
    method: lease.upload.method,
    headers,
    body: file,
    credentials: 'omit',
    redirect: 'error',
  })
  if (!response.ok) throw new Error(`图片直传失败（HTTP ${response.status}）`)

  const completed = await http.post(`/files/upload-leases/${encodeURIComponent(lease.lease_id)}/complete`)
  if (!completed?.key) throw new Error('服务器未确认图片上传完成')
  return completed.key
}
