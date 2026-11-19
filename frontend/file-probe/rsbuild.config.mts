import { defineConfig } from "@rsbuild/core";
import { pluginVue } from "@rsbuild/plugin-vue";
import { createBrowserDefines } from "../shared/rsbuild";

export default defineConfig(({ command }) => {
  return {
    plugins: [pluginVue()],
    html: { template: "./index.html" },
    source: {
      define: createBrowserDefines(command),
    },
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
  };
});
