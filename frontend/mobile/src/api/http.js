import axios from 'axios'
import { showToast } from 'vant'

const http = axios.create({ baseURL: '/api/v1', timeout: 15000 })

http.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

http.interceptors.response.use(
  (resp) => resp.data,
  (error) => {
    const detail = error.response?.data?.detail
    const message = typeof detail === 'string' ? detail : '请求失败，请稍后重试'
    if (error.response?.status === 401) {
      localStorage.removeItem('token')
      if (!location.pathname.startsWith('/auth')) location.href = '/auth/login'
    } else {
      showToast(message)
    }
    return Promise.reject(error)
  },
)

export default http
