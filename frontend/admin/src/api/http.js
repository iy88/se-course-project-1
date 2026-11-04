import axios from 'axios'
import { ElMessage } from 'element-plus'
import { useSession } from '../stores/session'

const http = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL,
  timeout: import.meta.env.VITE_API_TIMEOUT_MS,
})

http.interceptors.request.use((config) => {
  const token = localStorage.getItem('admin_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

http.interceptors.response.use(
  (resp) => resp.data,
  (error) => {
    const detail = error.response?.data?.detail
    const message = typeof detail === 'string' ? detail : '请求失败'
    const isLoginRequest = error.config?.url?.split('?')[0] === '/auth/login'
    if (error.response?.status === 401 && !isLoginRequest) {
      useSession().clear()
      if (location.pathname !== '/login') {
        location.href = '/login'
      }
    } else {
      ElMessage.error(message)
    }
    return Promise.reject(error)
  },
)

export default http
