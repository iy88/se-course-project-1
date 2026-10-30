import { useSession } from '../stores/session'

export function storedAdminUser() {
  return useSession().user
}

/** 读取服务端当前管理员资料；并发调用由 session 合并。 */
export async function ensureAdminUser() {
  try {
    return await useSession().refreshUser()
  } catch {
    return null
  }
}
