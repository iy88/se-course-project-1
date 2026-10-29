import http from './http'

const KEY = 'admin_user'

export function storedAdminUser() {
  try {
    return JSON.parse(localStorage.getItem(KEY) || 'null')
  } catch {
    return null
  }
}

/** 管理端当前账号；旧会话没有缓存时用 /auth/me 补齐，仅用于前端显示资格提示，服务端仍最终校验。 */
export async function ensureAdminUser() {
  const cached = storedAdminUser()
  if (cached?.id) return cached
  try {
    const user = await http.get('/auth/me')
    localStorage.setItem(KEY, JSON.stringify(user))
    return user
  } catch {
    return null
  }
}
