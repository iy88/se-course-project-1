import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { frontendSettings } from '../config.mjs'

// 管理端仅桌面 Web；开发代理指向本机后端
export default defineConfig({
  // 依赖预构建缓存放在本项目根目录，避免随共享 node_modules 被清理
  cacheDir: '.vite',
  plugins: [vue()],
  envDir: false,
  envPrefix: [],
  define: {
    'import.meta.env.VITE_API_BASE_URL': JSON.stringify(frontendSettings.apiBaseUrl),
    'import.meta.env.VITE_API_TIMEOUT_MS': JSON.stringify(frontendSettings.timeoutMs),
  },
  server: {
    port: 5174,
    proxy: {
      '/api': frontendSettings.proxyTarget,
      '/ws': { target: frontendSettings.proxyTarget.replace(/^http/, 'ws'), ws: true },
    },
  },
})
