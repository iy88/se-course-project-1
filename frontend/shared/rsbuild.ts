import { defineConfig } from "@rsbuild/core";
import { pluginVue } from "@rsbuild/plugin-vue";

export function createBrowserDefines(command: string) {
  return {
    // Vue's ESM bundler build reads NODE_ENV directly instead of guarding process.
    "process.env.NODE_ENV": JSON.stringify(command === "dev" ? "development" : "production"),
  };
}

export function createWebConfig(port: number) {
  return defineConfig(({ command }) => {
    return {
      plugins: [pluginVue()],
      html: { template: "./index.html" },
      source: {
        define: createBrowserDefines(command),
      },
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
    };
  });
}
