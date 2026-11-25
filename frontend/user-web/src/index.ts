import { createApp } from "vue";
import App from "./App.vue";
import { startNetworkStatus } from "./app/network";
import { registerServiceWorker } from "./app/pwa";
import { router } from "./app/router";
import "./styles/base.css";

startNetworkStatus();
registerServiceWorker();
createApp(App).use(router).mount("#root");
