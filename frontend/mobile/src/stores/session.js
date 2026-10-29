import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import http from '../api/http'

export const useSession = defineStore('session', () => {
  const user = ref(JSON.parse(localStorage.getItem('user') || 'null'))
  const unreadNotifications = ref(0)
  const unreadMessages = ref(0)

  const banned = computed(() => user.value?.status === 'banned')
  const hasFrozenTrade = computed(() => user.value?.has_frozen_trade === true)

  function setSession(token, userData) {
    localStorage.setItem('token', token)
    localStorage.setItem('user', JSON.stringify(userData))
    user.value = userData
  }

  function updateUser(userData) {
    localStorage.setItem('user', JSON.stringify(userData))
    user.value = userData
  }

  /** 刷新当前账户限制（含 has_frozen_trade）；失败时保留旧值，由服务端继续兜底。 */
  let refreshPromise = null
  async function refreshUser() {
    // 路由切换与页面加载可能同时触发；合并同一时刻的刷新请求，避免重复风暴，仍以服务端最新响应为准。
    if (!refreshPromise) {
      refreshPromise = http
        .get('/auth/me')
        .then((data) => {
          updateUser(data)
          return data
        })
        .finally(() => {
          refreshPromise = null
        })
    }
    return refreshPromise
  }

  function clear() {
    localStorage.removeItem('token')
    localStorage.removeItem('user')
    user.value = null
    unreadNotifications.value = 0
    unreadMessages.value = 0
  }

  return {
    user,
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
