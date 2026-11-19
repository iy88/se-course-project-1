import { defineConfig } from "@rsbuild/core";
import { pluginVue } from "@rsbuild/plugin-vue";

export default defineConfig({
  plugins: [pluginVue()],
  html: { template: "./index.html" },
  server: {
    host: "127.0.0.1",
    port: 3002,
    strictPort: true,
    proxy: {
      "/__dev/file-probe": {
        target: process.env.API_PROXY_TARGET ?? "http://127.0.0.1:8080",
        changeOrigin: true,
      },
    },
  },
});
