import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import Components from 'unplugin-vue-components/vite'
import { VantResolver } from '@vant/auto-import-resolver'
import { VitePWA } from 'vite-plugin-pwa'
import { frontendSettings } from '../config.mjs'

// Mobile user-side PWA: installable with offline app-shell caching; business data always goes over the network
export default defineConfig({
  // Keep the dependency prebundle cache in this project's root so it is not removed with the shared node_modules
  cacheDir: '.vite',
  plugins: [
    vue(),
    // The full stylesheet is imported centrally by main.js via vant/lib/index.css; on-demand style side effects are disabled
    // so late-injected vant/es/*.css from lazy route loading cannot disturb cascade order (e.g. .van-popup--center
    // overriding the width of the functional dialog .van-dialog).
    Components({ resolvers: [VantResolver({ importStyle: false })] }),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['favicon.svg'],
      manifest: {
        name: '校园二手交易平台',
        short_name: '校园二手',
        description: '校园闲置物品发布、检索、沟通与交易记录',
        theme_color: '#2f6b4f',
        background_color: '#eef1ee',
        display: 'standalone',
        start_url: '/',
        icons: [
          { src: 'icons/icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: 'icons/icon-512.png', sizes: '512x512', type: 'image/png' },
        ],
      },
      workbox: {
        globPatterns: ['**/*.{js,css,html,svg,png,woff2}'],
        navigateFallback: '/index.html',
        navigateFallbackDenylist: [/^\/api\//],
        runtimeCaching: [
          {
            urlPattern: /^\/api\/v1\/files\//,
            handler: 'CacheFirst',
            options: {
              cacheName: 'file-cache',
              expiration: { maxEntries: 200, maxAgeSeconds: 60 * 60 },
            },
          },
        ],
      },
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
    port: 5173,
    proxy: {
      '/api': frontendSettings.proxyTarget,
      '/ws': { target: frontendSettings.wsProxyTarget, ws: true },
    },
  },
})
