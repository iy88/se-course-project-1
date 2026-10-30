import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/login', component: () => import('../views/Login.vue'), meta: { public: true } },
  {
    path: '/',
    component: () => import('../views/Layout.vue'),
    children: [
      { path: '', redirect: '/cases' },
      { path: 'cases', component: () => import('../views/Cases.vue'), meta: { title: '待处理池' } },
      { path: 'cases/:id', component: () => import('../views/CaseDetail.vue'), meta: { title: '事项处理' } },
      { path: 'reports', component: () => import('../views/Reports.vue'), meta: { title: '举报核查' } },
      { path: 'products', component: () => import('../views/AdminProducts.vue'), meta: { title: '商品管理' } },
      { path: 'trades', component: () => import('../views/AdminTrades.vue'), meta: { title: '交易处置' } },
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

router.beforeEach((to) => {
  if (!to.meta.public && !localStorage.getItem('admin_token')) return '/login'
  return true
})

export default router
