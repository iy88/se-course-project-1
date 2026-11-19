import { defineConfig } from "@rsbuild/core";
import { pluginVue } from "@rsbuild/plugin-vue";

export function createWebConfig(port: number) {
  return defineConfig({
    plugins: [pluginVue()],
    html: { template: "./index.html" },
    server: {
      host: "127.0.0.1",
      port,
      strictPort: true,
      proxy: {
        "/api/v1": {
          target: process.env.API_PROXY_TARGET ?? "http://127.0.0.1:8080",
          changeOrigin: true,
        },
      },
    },
  });
}
