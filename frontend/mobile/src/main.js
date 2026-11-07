import { createApp } from 'vue'
import { createPinia } from 'pinia'
// The full stylesheet covers template components and functional APIs (showConfirmDialog, showToast, etc.).
// On-demand styles are disabled in vite.config.js so lazy-loaded styles cannot inject later and override this file.
import 'vant/lib/index.css'
import App from './App.vue'
import router from './router'
import { useSession } from './stores/session'
import './style.css'

const app = createApp(App)
const pinia = createPinia()
app.use(pinia)
app.use(router)

// Re-read account restrictions on every business page entry instead of reading has_frozen_trade only at login.
const session = useSession(pinia)
router.afterEach((to) => {
  if (!to.meta.public && localStorage.getItem('token')) {
    session.refreshUser().catch(() => {})
  }
})

app.mount('#app')
