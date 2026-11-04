import { createApp } from 'vue'
import { createPinia } from 'pinia'
import 'element-plus/dist/index.css'
import './style.css'
import App from './App.vue'
import router from './router'
import { useSession } from './stores/session'

const app = createApp(App)
const pinia = createPinia()
app.use(pinia)
app.use(router)
const session = useSession(pinia)
router.afterEach((to) => {
  if (!to.meta.public && localStorage.getItem('admin_token')) {
    session.refreshUser().catch(() => {})
  }
})

app.mount('#app')
