import { createRouter, createWebHistory } from 'vue-router'
import { useSession } from '../stores/session'

const routes = [
  { path: '/auth/login', component: () => import('../views/AuthLogin.vue'), meta: { public: true } },
  { path: '/auth/register', component: () => import('../views/AuthRegister.vue'), meta: { public: true } },
  { path: '/auth/forgot', component: () => import('../views/AuthForgot.vue'), meta: { public: true } },
  {
    path: '/',
    component: () => import('../views/Layout.vue'),
    children: [
      { path: '', redirect: '/home' },
      { path: 'home', component: () => import('../views/Home.vue'), meta: { title: '首页' } },
      { path: 'publish', component: () => import('../views/Publish.vue'), meta: { title: '发布' } },
      { path: 'messages', component: () => import('../views/Messages.vue'), meta: { title: '消息' } },
      { path: 'notifications', component: () => import('../views/Notifications.vue'), meta: { title: '通知中心' } },
      { path: 'me', component: () => import('../views/Me.vue'), meta: { title: '我的' } },
    ],
  },
  { path: '/products/:id', component: () => import('../views/ProductDetail.vue') },
  {
    path: '/products/:id/review-records',
    component: () => import('../views/ProductReviewRecords.vue'),
    meta: { title: '审核记录' },
  },
  { path: '/products/:id/edit', component: () => import('../views/Publish.vue'), meta: { title: '编辑商品' } },
  { path: '/users/:id', component: () => import('../views/UserProfile.vue') },
  { path: '/trades/:id', component: () => import('../views/TradeDetail.vue') },
  { path: '/conversations/:id', component: () => import('../views/Chat.vue') },
  { path: '/cases/:id', component: () => import('../views/CaseDetail.vue') },
  { path: '/me/products', component: () => import('../views/MyProducts.vue') },
  { path: '/me/trades', component: () => import('../views/MyTrades.vue') },
  { path: '/me/favorites', component: () => import('../views/MyFavorites.vue') },
  { path: '/me/reviews', component: () => import('../views/MyReviews.vue') },
  { path: '/me/reports', component: () => import('../views/MyReports.vue') },
  { path: '/me/settings', component: () => import('../views/Settings.vue') },
]

routes.push({ path: '/:pathMatch(.*)*', redirect: '/' })

const router = createRouter({ history: createWebHistory(), routes })

router.beforeEach(async (to) => {
  const session = useSession()
  const token = localStorage.getItem('token')
  const login = { path: '/auth/login', query: { redirect: to.fullPath } }
  if (!token) {
    if (session.user) session.clear()
    return to.meta.public ? true : login
  }

  // 已保存的 token 不是已认证状态：先校验服务端身份，再渲染受保护页面。
  if (session.verifiedToken !== token) {
    try {
      await session.refreshUser()
    } catch {
      // 401 或管理员资格变化清理 token；网络等暂时性错误不应误删会话。
      if (!localStorage.getItem('token')) return to.meta.public ? true : login
      return false
    }
  }
  if (to.meta.public) return '/home'
  return true
})

export default router
