import { createRouter, createWebHistory } from 'vue-router'
import { showDialog } from 'vant'

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

router.beforeEach((to) => {
  if (!to.meta.public && !localStorage.getItem('token')) {
    showDialog({ title: '请先登录', message: '访客仅可使用注册、登录和忘记密码入口' }).catch(() => {})
    return '/auth/login'
  }
  return true
})

export default router
