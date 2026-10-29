import { createApp } from 'vue'
import { createPinia } from 'pinia'
import 'vant/lib/index.css'
import App from './App.vue'
import router from './router'
import { useSession } from './stores/session'
import './style.css'

const app = createApp(App)
const pinia = createPinia()
app.use(pinia)
app.use(router)

// 每次进入业务页面重新读取账户限制，避免只在登录时读取 has_frozen_trade。
const session = useSession(pinia)
router.afterEach((to) => {
  if (!to.meta.public && localStorage.getItem('token')) {
    session.refreshUser().catch(() => {})
  }
})

app.mount('#app')
