import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useSession = defineStore('session', () => {
  const user = ref(JSON.parse(localStorage.getItem('user') || 'null'))
  const unreadNotifications = ref(0)
  const unreadMessages = ref(0)

  function setSession(token, userData) {
    localStorage.setItem('token', token)
    localStorage.setItem('user', JSON.stringify(userData))
    user.value = userData
  }

  function updateUser(userData) {
    localStorage.setItem('user', JSON.stringify(userData))
    user.value = userData
  }

  function clear() {
    localStorage.removeItem('token')
    localStorage.removeItem('user')
    user.value = null
    unreadNotifications.value = 0
    unreadMessages.value = 0
  }

  return { user, unreadNotifications, unreadMessages, setSession, updateUser, clear }
})
