import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import Components from 'unplugin-vue-components/vite'
import { VantResolver } from '@vant/auto-import-resolver'
import { VitePWA } from 'vite-plugin-pwa'

// 移动端用户侧 PWA：可安装、离线壳缓存；业务数据始终走网络
export default defineConfig({
  plugins: [
    vue(),
    Components({ resolvers: [VantResolver()] }),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['favicon.svg'],
      manifest: {
        name: '校园二手交易平台',
        short_name: '校园二手',
        description: '校园闲置物品发布、检索、沟通与交易记录',
        theme_color: '#1989fa',
        background_color: '#f7f8fa',
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
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/ws': { target: 'ws://127.0.0.1:8000', ws: true },
    },
  },
})
