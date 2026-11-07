import { useSession } from '../stores/session'

export function storedAdminUser() {
  return useSession().user
}

/** Read the current admin profile from the server; concurrent calls are merged by the session store. */
export async function ensureAdminUser() {
  try {
    return await useSession().refreshUser()
  } catch {
    return null
  }
}
