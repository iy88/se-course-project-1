import { defineStore } from 'pinia'
import { ref } from 'vue'
import http from '../api/http'

export const useSession = defineStore('session', () => {
  let cached = null
  try {
    cached = JSON.parse(localStorage.getItem('admin_user') || 'null')
  } catch {
    localStorage.removeItem('admin_user')
  }
  if (cached) { cached.avatar_url = null; cached.avatar_pending_url = null }
  const user = ref(cached)
  let refreshPromise = null

  function updateUser(data) {
    user.value = data
    localStorage.setItem('admin_user', JSON.stringify(data))
  }

  function setSession(token, data) {
    localStorage.setItem('admin_token', token)
    updateUser(data)
  }

  function clear() {
    localStorage.removeItem('admin_token')
    localStorage.removeItem('admin_user')
    user.value = null
  }

  async function refreshUser() {
    if (!refreshPromise) {
      refreshPromise = http.get('/auth/me').then((data) => {
        if (data.role !== 'admin' || data.status !== 'normal') {
          clear()
          location.href = '/login'
          throw new Error('管理员账户资格已变更')
        }
        updateUser(data)
        return data
      }).finally(() => { refreshPromise = null })
    }
    return refreshPromise
  }

  return { user, setSession, updateUser, refreshUser, clear }
})
