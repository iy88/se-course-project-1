import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 管理端仅桌面 Web；开发代理指向本机后端
export default defineConfig({
  // 依赖预构建缓存放在本项目根目录，避免随共享 node_modules 被清理
  cacheDir: '.vite',
  plugins: [vue()],
  server: {
    port: 5174,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/ws': { target: 'ws://127.0.0.1:8000', ws: true },
    },
  },
})
