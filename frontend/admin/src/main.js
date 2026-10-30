import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import 'element-plus/dist/index.css'
import './style.css'
import App from './App.vue'
import router from './router'
import { useSession } from './stores/session'

const app = createApp(App)
const pinia = createPinia()
app.use(pinia)
app.use(router)
app.use(ElementPlus, { locale: zhCn })
const session = useSession(pinia)
router.afterEach((to) => {
  if (!to.meta.public && localStorage.getItem('admin_token')) {
    session.refreshUser().catch(() => {})
  }
})

app.mount('#app')
