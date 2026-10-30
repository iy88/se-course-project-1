import axios from 'axios'
import { ElMessage } from 'element-plus'

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
    if (error.response?.status === 401) {
      localStorage.removeItem('admin_token')
      if (!location.pathname.includes('/login')) location.href = '/login'
    } else {
      ElMessage.error(message)
    }
    return Promise.reject(error)
  },
)

export default http
