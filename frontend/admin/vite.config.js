import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 管理端仅桌面 Web；开发代理指向本机后端
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5174,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/ws': { target: 'ws://127.0.0.1:8000', ws: true },
    },
  },
})
