import { createRouter, createWebHistory } from 'vue-router'
import { useSession } from '../stores/session'

const routes = [
  { path: '/login', component: () => import('../views/Login.vue'), meta: { public: true } },
  {
    path: '/',
    component: () => import('../views/Layout.vue'),
    children: [
      { path: '', redirect: '/cases' },
      { path: 'cases', component: () => import('../views/Cases.vue'), meta: { title: '待处理池' } },
      { path: 'my-cases', component: () => import('../views/MyCases.vue'), meta: { title: '我的审核' } },
      { path: 'cases/:id', component: () => import('../views/CaseDetail.vue'), meta: { title: '事项处理' } },
      { path: 'products', component: () => import('../views/AdminProducts.vue'), meta: { title: '商品管理' } },
      { path: 'products/:id', component: () => import('../views/ProductDetail.vue'), meta: { title: '商品详情预览' } },
      { path: 'users', component: () => import('../views/AdminUsers.vue'), meta: { title: '账户管理' } },
      { path: 'categories', component: () => import('../views/Categories.vue'), meta: { title: '分类标签' } },
      { path: 'prohibited', component: () => import('../views/Prohibited.vue'), meta: { title: '禁发范围' } },
      { path: 'audit', component: () => import('../views/Audit.vue'), meta: { title: '审计查询' } },
      { path: 'stats', component: () => import('../views/Stats.vue'), meta: { title: '数据统计' } },
    ],
  },
]

routes.push({ path: '/:pathMatch(.*)*', redirect: '/' })

const router = createRouter({ history: createWebHistory(), routes })

router.beforeEach(async (to) => {
  const session = useSession()
  const token = localStorage.getItem('admin_token')
  const login = { path: '/login', query: { redirect: to.fullPath } }
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
      if (!localStorage.getItem('admin_token')) return to.meta.public ? true : login
      return false
    }
  }
  if (to.meta.public) return '/cases'
  return true
})

export default router
