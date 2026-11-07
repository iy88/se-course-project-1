import { createRouter, createWebHistory } from 'vue-router'
import { useSession } from '../stores/session'
import { resolveRefreshFailure } from './guard'

const routes = [
  { path: '/auth/login', component: () => import('../views/AuthLogin.vue'), meta: { public: true } },
  { path: '/auth/register', component: () => import('../views/AuthRegister.vue'), meta: { public: true } },
  { path: '/auth/forgot', component: () => import('../views/AuthForgot.vue'), meta: { public: true } },
  { path: '/offline', component: () => import('../views/Offline.vue'), meta: { public: true, offline: true } },
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
  { path: '/products/:id/edit-history', component: () => import('../views/ProductEditHistory.vue'), meta: { title: '商品编辑历史' } },
  { path: '/products/:id/edit', component: () => import('../views/Publish.vue'), meta: { title: '编辑商品' } },
  { path: '/users/:id', component: () => import('../views/UserProfile.vue') },
  { path: '/trades/:id', component: () => import('../views/TradeDetail.vue') },
  { path: '/conversations/:id', name: 'chat', component: () => import('../views/Chat.vue') },
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
  // The offline fallback page holds no business data and must be reachable before any token refresh.
  if (to.meta.offline) return true
  const session = useSession()
  const token = localStorage.getItem('token')
  const login = { path: '/auth/login', query: { redirect: to.fullPath } }
  if (!token) {
    if (session.user) session.clear()
    return to.meta.public ? true : login
  }

  // A stored token is not an authenticated state: verify the server identity before rendering protected pages.
  if (session.verifiedToken !== token) {
    try {
      await session.refreshUser()
    } catch (error) {
      // On 401 the HTTP interceptor has already cleared the token, so hasToken=false → login, reusing the existing session-invalidation flow.
      // When offline or the server is temporarily unavailable and a cached user exists, allow the cached app shell (pages report load failures);
      // 403/404 and internal program errors are never mistaken for offline; without a cached user, show the public offline page.
      const decision = resolveRefreshFailure(error, {
        hasToken: Boolean(localStorage.getItem('token')),
        hasCachedUser: Boolean(session.user),
      })
      if (decision === 'login') return to.meta.public ? true : login
      if (decision === 'allow-shell') return true
      // With a token but no cached user, show a standalone fallback page that leaks no business data instead of cancelling navigation and leaving a blank screen.
      if (decision === 'offline') {
        return { path: '/offline', query: { redirect: to.fullPath } }
      }
      return false
    }
  }
  if (to.meta.public) return '/home'
  return true
})

export default router
