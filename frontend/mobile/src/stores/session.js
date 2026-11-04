import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import http from '../api/http'

export const useSession = defineStore('session', () => {
  let cached = null
  try { cached = JSON.parse(localStorage.getItem('user') || 'null') } catch { localStorage.removeItem('user') }
  // 临时图片链接由本轮身份刷新提供，避免先请求旧链接再替换为新签名。
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
  }

  function updateUser(userData) {
    localStorage.setItem('user', JSON.stringify(userData))
    user.value = userData
  }

  /** 刷新当前账户限制（含 has_frozen_trade）；失败时保留旧值，由服务端继续兜底。 */
  let refreshPromise = null
  async function refreshUser() {
    // 合并路由与页面触发的身份刷新；退出后不允许旧响应恢复用户资料。
    const token = localStorage.getItem('token')
    if (!token) throw new Error('未登录')
    // 路由切换与页面加载可能同时触发；合并同一时刻的刷新请求，避免重复风暴，仍以服务端最新响应为准。
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
