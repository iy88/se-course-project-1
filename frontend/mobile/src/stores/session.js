import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import http from '../api/http'

export const useSession = defineStore('session', () => {
  let cached = null
  try { cached = JSON.parse(localStorage.getItem('user') || 'null') } catch { localStorage.removeItem('user') }
  // Temporary image URLs are supplied by this round of identity refresh, avoiding an old URL request before replacing it with a new signature.
  if (cached) { cached.avatar_url = null; cached.avatar_pending_url = null }
  const user = ref(localStorage.getItem('token') ? cached : null)
  const verifiedToken = ref(null)
  const unreadNotifications = ref(0)
  const unreadMessages = ref(0)

  const banned = computed(() => user.value?.status === 'banned')
  const hasFrozenTrade = computed(() => user.value?.has_frozen_trade === true)

  function setSession(token, userData) {
    verifiedToken.value = token
    localStorage.setItem('token', token)
    localStorage.setItem('user', JSON.stringify(userData))
    user.value = userData
    if (typeof window !== 'undefined') window.dispatchEvent(new Event('app:session-changed'))
  }

  function updateUser(userData) {
    localStorage.setItem('user', JSON.stringify(userData))
    user.value = userData
  }

  /** Refresh current account restrictions (including has_frozen_trade); keep previous values on failure and let the server continue to enforce them. */
  let refreshPromise = null
  async function refreshUser() {
    // Merge identity refreshes triggered by routes and pages; after logout, stale responses must not restore user data.
    const token = localStorage.getItem('token')
    if (!token) throw new Error('未登录')
    // Route switches and page loads may fire together; merge same-instant refresh requests to avoid a request storm while still honoring the server's latest response.
    if (!refreshPromise) {
      refreshPromise = http
        .get('/auth/me')
        .then((data) => {
          if (localStorage.getItem('token') !== token) throw new Error('登录状态已变化')
          updateUser(data)
          verifiedToken.value = token
          return data
        })
        .finally(() => {
          refreshPromise = null
        })
    }
    return refreshPromise
  }

  function clear() {
    verifiedToken.value = null
    localStorage.removeItem('token')
    localStorage.removeItem('user')
    user.value = null
    unreadNotifications.value = 0
    unreadMessages.value = 0
    if (typeof window !== 'undefined') window.dispatchEvent(new Event('app:session-cleared'))
  }

  return {
    user,
    verifiedToken,
    unreadNotifications,
    unreadMessages,
    banned,
    hasFrozenTrade,
    setSession,
    updateUser,
    refreshUser,
    clear,
  }
})
