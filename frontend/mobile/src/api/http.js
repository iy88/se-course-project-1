import axios from 'axios'
import * as textTools from './text'
import { validateTextRequest } from '../../../shared/textRequests.mjs'
import { showToast } from 'vant'
import { useSession } from '../stores/session'

const http = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL,
  timeout: import.meta.env.VITE_API_TIMEOUT_MS,
})

http.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return validateTextRequest(config, textTools)
})

http.interceptors.response.use(
  (resp) => resp.data,
  (error) => {
    const rawDetail = error.response?.data?.detail
    const detail = Array.isArray(rawDetail) ? rawDetail.map(item => item.msg?.replace(/^Value error, /, '')).filter(Boolean).join('；') : rawDetail
    // No response means offline or unreachable: prompt to check the network, separate from business error details that have a response.
    let message = '请求失败，请稍后重试'
    if (!error.response) message = '网络不可用，请检查连接后重试'
    else if (typeof detail === 'string') message = detail
    const isLoginRequest = error.config?.url?.split('?')[0] === '/auth/login'
    if (error.response?.status === 401 && !isLoginRequest) {
      useSession().clear()
      if (!location.pathname.startsWith('/auth')) {
        location.href = '/auth/login'
      }
    } else {
      showToast(message)
    }
    return Promise.reject(error)
  },
)

export default http
