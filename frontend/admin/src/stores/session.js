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
  const user = ref(localStorage.getItem('admin_token') ? cached : null)
  const verifiedToken = ref(null)
  let refreshPromise = null

  function updateUser(data) {
    user.value = data
    localStorage.setItem('admin_user', JSON.stringify(data))
  }

  function setSession(token, data) {
    verifiedToken.value = token
    localStorage.setItem('admin_token', token)
    updateUser(data)
  }

  function clear() {
    verifiedToken.value = null
    localStorage.removeItem('admin_token')
    localStorage.removeItem('admin_user')
    user.value = null
  }

  async function refreshUser() {
    const token = localStorage.getItem('admin_token')
    if (!token) throw new Error('未登录')
    if (!refreshPromise) {
      refreshPromise = http.get('/auth/me').then((data) => {
        if (localStorage.getItem('admin_token') !== token) throw new Error('登录状态已变化')
        if (data.role !== 'admin' || data.status !== 'normal') {
          clear()
          throw new Error('管理员账户资格已变更')
        }
        updateUser(data)
        verifiedToken.value = token
        return data
      }).finally(() => { refreshPromise = null })
    }
    return refreshPromise
  }

  return { user, verifiedToken, setSession, updateUser, refreshUser, clear }
})
