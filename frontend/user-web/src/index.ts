import { createPinia } from "pinia";
import { createApp } from "vue";
import App from "./App.vue";
import { startNetworkStatus } from "./app/network";
import { registerServiceWorker } from "./app/pwa";
import { router } from "./app/router";
import { installToastBridge } from "./app/toast-bridge";
import "./styles/base.css";

startNetworkStatus();
registerServiceWorker();
const pinia = createPinia();
installToastBridge(pinia);
createApp(App).use(pinia).use(router).mount("#root");
