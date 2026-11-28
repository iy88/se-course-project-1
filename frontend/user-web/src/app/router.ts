/*
 * Application routes and the authentication guard.
 *
 * Routes are declared with an explicit `meta.requiresAuth` flag so the guard has
 * a single decision point; the shell decides how the navigation is presented.
 */
import { createRouter, createWebHistory, START_LOCATION, type RouteRecordRaw } from "vue-router";
import { ensureSession, refreshSession, session } from "./session";
import { notify } from "./toast-bridge";

declare module "vue-router" {
  interface RouteMeta {
    /** Route is reachable without a session. */
    anonymous?: boolean;
    /** Route needs a valid session; unauthenticated visitors go to the login page. */
    requiresAuth?: boolean;
    /** Route opens a form that requires an unrestricted account. */
    requiresWrite?: boolean;
    /** Navigation label used by the shell when the route is a primary entry. */
    navLabel?: string;
    /** Deterministic parent used when a deep link has no in-app history. */
    backTo?: string;
    /** Dynamic parameter names copied from the current route into the fallback. */
    backParams?: string[];
    /** Parent page name announced by the mobile back button. */
    backLabel?: string;
  }
}

export const routes: RouteRecordRaw[] = [
  {
    path: "/",
    name: "home",
    component: () => import("../views/products/ProductSearchView.vue"),
    meta: { requiresAuth: true, navLabel: "逛逛" },
  },
  {
    path: "/search",
    name: "product-search",
    component: () => import("../views/products/ProductSearchView.vue"),
    meta: { requiresAuth: true, backTo: "home", backLabel: "逛逛" },
  },
  {
    path: "/login",
    name: "login",
    component: () => import("../views/auth/LoginView.vue"),
    meta: { anonymous: true },
  },
  {
    path: "/register",
    name: "register",
    component: () => import("../views/auth/RegisterView.vue"),
    meta: { anonymous: true, backTo: "login", backLabel: "登录" },
  },
  {
    path: "/reset-password",
    name: "reset-password",
    component: () => import("../views/auth/ResetPasswordView.vue"),
    meta: { anonymous: true, backTo: "login", backLabel: "登录" },
  },
  {
    path: "/products/new",
    name: "product-create",
    component: () => import("../views/products/ProductEditorView.vue"),
    meta: { requiresAuth: true, requiresWrite: true, backTo: "my-products", backLabel: "我的商品" },
  },
  {
    path: "/products/:productId",
    name: "product-detail",
    component: () => import("../views/products/ProductDetailView.vue"),
    meta: { requiresAuth: true, backTo: "home", backLabel: "逛逛" },
  },
  {
    path: "/products/:productId/edit",
    name: "product-edit",
    component: () => import("../views/products/ProductEditorView.vue"),
    meta: {
      requiresAuth: true,
      requiresWrite: true,
      backTo: "product-detail",
      backParams: ["productId"],
      backLabel: "商品详情",
    },
  },
  {
    path: "/me",
    name: "me",
    component: () => import("../views/me/MeOverviewView.vue"),
    meta: { requiresAuth: true, navLabel: "我的" },
  },
  {
    path: "/me/products",
    name: "my-products",
    component: () => import("../views/products/MyProductsView.vue"),
    meta: { requiresAuth: true, backTo: "me", backLabel: "我的" },
  },
  {
    path: "/me/favorites",
    name: "my-favorites",
    component: () => import("../views/products/FavoritesView.vue"),
    meta: { requiresAuth: true, backTo: "me", backLabel: "我的" },
  },
  {
    path: "/me/settings",
    name: "settings",
    component: () => import("../views/account/SettingsView.vue"),
    meta: { requiresAuth: true, backTo: "me", backLabel: "我的" },
  },
  {
    path: "/me/notifications",
    name: "notifications",
    component: () => import("../views/notifications/NotificationListView.vue"),
    meta: { requiresAuth: true, navLabel: "消息" },
  },
  {
    path: "/me/notifications/:notificationId",
    name: "notification-detail",
    component: () => import("../views/notifications/NotificationDetailView.vue"),
    meta: { requiresAuth: true, backTo: "notifications", backLabel: "通知" },
  },
  {
    path: "/me/trades",
    name: "my-trades",
    component: () => import("../views/trades/TradeListView.vue"),
    meta: { requiresAuth: true, backTo: "me", backLabel: "我的" },
  },
  {
    path: "/me/reviews",
    name: "my-reviews",
    component: () => import("../views/me/MyReviewsView.vue"),
    meta: { requiresAuth: true, backTo: "me", backLabel: "我的" },
  },
  {
    path: "/me/todos",
    name: "my-todos",
    component: () => import("../views/me/MyTodosView.vue"),
    meta: { requiresAuth: true, backTo: "me", backLabel: "我的" },
  },
  {
    path: "/me/cases",
    name: "my-cases",
    component: () => import("../views/cases/CaseListView.vue"),
    meta: { requiresAuth: true, backTo: "me", backLabel: "我的" },
  },
  {
    path: "/me/banned-items",
    name: "banned-items",
    component: () => import("../views/products/BannedScopeView.vue"),
    meta: { requiresAuth: true, backTo: "me", backLabel: "我的" },
  },
  {
    path: "/trades/:tradeId",
    name: "trade-detail",
    component: () => import("../views/trades/TradeDetailView.vue"),
    meta: { requiresAuth: true, backTo: "my-trades", backLabel: "交易列表" },
  },
  {
    path: "/conversations",
    component: () => import("../views/conversations/ConversationLayout.vue"),
    meta: { requiresAuth: true, navLabel: "消息" },
    children: [
      {
        path: "",
        name: "conversations",
        component: () => import("../views/conversations/ConversationIndex.vue"),
      },
      {
        path: ":kind/:conversationId",
        name: "conversation",
        component: () => import("../views/conversations/ConversationThread.vue"),
      },
    ],
  },
  {
    path: "/case-results",
    name: "case-results",
    component: () => import("../views/cases/CaseResultsView.vue"),
    meta: { requiresAuth: true, backTo: "my-cases", backLabel: "事项列表" },
  },
  {
    path: "/cases/:caseId",
    name: "case-detail",
    component: () => import("../views/cases/CaseDetailView.vue"),
    meta: { requiresAuth: true, backTo: "my-cases", backLabel: "事项列表" },
  },
  {
    path: "/report",
    name: "report",
    component: () => import("../views/cases/ReportView.vue"),
    meta: { requiresAuth: true, requiresWrite: true, backTo: "my-cases", backLabel: "事项列表" },
  },
  {
    path: "/:pathMatch(.*)*",
    name: "not-found",
    component: () => import("../views/NotFoundView.vue"),
    meta: { requiresAuth: true, backTo: "home", backLabel: "逛逛" },
  },
];

export const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: (to, _from, savedPosition) => {
    if (to.name === "product-detail" && /^#comment-[1-9][0-9]*$/.test(to.hash)) return false;
    if (to.name === "case-detail" && /^#case-message-[1-9][0-9]*$/.test(to.hash)) return false;
    return savedPosition ?? { top: 0 };
  },
});

router.beforeEach(async (to, from) => {
  if (to.meta.requiresWrite && session.isAuthenticated.value) {
    await refreshSession().catch(() => {
      // Use the last known state when identity refresh is temporarily unavailable.
    });
  } else {
    await ensureSession();
  }
  if (to.meta.requiresAuth && !session.isAuthenticated.value) {
    return { name: "login", query: { redirect: to.fullPath } };
  }
  if (to.meta.anonymous && session.isAuthenticated.value) {
    return { name: "home" };
  }
  if (to.meta.requiresWrite && session.account.value?.write_restricted) {
    notify.warn("当前账户处于限制状态，该操作暂不可用。可在「我的事项」查看处理结果。");
    return from === START_LOCATION ? { name: "home", replace: true } : false;
  }
  return true;
});
