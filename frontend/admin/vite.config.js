import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'
import { frontendSettings } from '../config.mjs'

// Admin is desktop web only; the dev proxy points at the local backend
export default defineConfig({
  // Keep the dependency prebundle cache in this project's root so it is not removed with the shared node_modules
  cacheDir: '.vite',
  plugins: [
    vue(),
    Components({
      dts: false,
      // Keep the existing full CSS import first to avoid changing style injection order and causing UI regressions.
      resolvers: [ElementPlusResolver({ importStyle: false })],
    }),
  ],
  envDir: false,
  envPrefix: [],
  define: {
    'import.meta.env.VITE_API_BASE_URL': JSON.stringify(frontendSettings.apiBaseUrl),
    'import.meta.env.VITE_API_TIMEOUT_MS': JSON.stringify(frontendSettings.timeoutMs),
  },
  server: {
    host: '0.0.0.0',
    port: 5174,
    proxy: {
      '/api': frontendSettings.proxyTarget,
      '/ws': { target: frontendSettings.wsProxyTarget, ws: true },
    },
  },
})
