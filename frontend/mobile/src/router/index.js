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
  // 离线兜底页不含业务数据，必须在任何 token 刷新前允许直接进入。
  if (to.meta.offline) return true
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
    } catch (error) {
      // 401 时 http 拦截器已清理 token，此处 hasToken=false → login，沿用既有会话失效流程。
      // 离线/服务端暂时不可用且本地有缓存用户时放行已缓存的应用壳（由页面提示加载失败）；
      // 403/404 及程序内部异常不会被误认成离线；没有缓存用户时显示公共离线页。
      const decision = resolveRefreshFailure(error, {
        hasToken: Boolean(localStorage.getItem('token')),
        hasCachedUser: Boolean(session.user),
      })
      if (decision === 'login') return to.meta.public ? true : login
      if (decision === 'allow-shell') return true
      // 有 token 但没有缓存的用户时，展示不泄露业务数据的独立兜底页，而不是取消导航导致白屏。
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
