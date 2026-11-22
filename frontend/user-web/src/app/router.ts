/*
 * Application routes and the authentication guard.
 *
 * Routes are declared with an explicit `meta.requiresAuth` flag so the guard has
 * a single decision point; the shell decides how the navigation is presented.
 */
import { createRouter, createWebHistory, type RouteRecordRaw } from "vue-router";
import { ensureSession, session } from "./session";

declare module "vue-router" {
  interface RouteMeta {
    /** Route is reachable without a session. */
    anonymous?: boolean;
    /** Route needs a valid session; unauthenticated visitors go to the login page. */
    requiresAuth?: boolean;
    /** Navigation label used by the shell when the route is a primary entry. */
    navLabel?: string;
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
    path: "/login",
    name: "login",
    component: () => import("../views/auth/LoginView.vue"),
    meta: { anonymous: true },
  },
  {
    path: "/register",
    name: "register",
    component: () => import("../views/auth/RegisterView.vue"),
    meta: { anonymous: true },
  },
  {
    path: "/reset-password",
    name: "reset-password",
    component: () => import("../views/auth/ResetPasswordView.vue"),
    meta: { anonymous: true },
  },
  {
    path: "/products/new",
    name: "product-create",
    component: () => import("../views/products/ProductEditorView.vue"),
    meta: { requiresAuth: true },
  },
  {
    path: "/products/:productId",
    name: "product-detail",
    component: () => import("../views/products/ProductDetailView.vue"),
    meta: { requiresAuth: true },
  },
  {
    path: "/products/:productId/edit",
    name: "product-edit",
    component: () => import("../views/products/ProductEditorView.vue"),
    meta: { requiresAuth: true },
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
    meta: { requiresAuth: true },
  },
  {
    path: "/me/profile",
    name: "profile",
    component: () => import("../views/account/ProfileView.vue"),
    meta: { requiresAuth: true },
  },
  {
    path: "/me/security",
    name: "security",
    component: () => import("../views/account/SecurityView.vue"),
    meta: { requiresAuth: true },
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
    meta: { requiresAuth: true },
  },
  {
    path: "/me/trades",
    name: "my-trades",
    component: () => import("../views/trades/TradeListView.vue"),
    meta: { requiresAuth: true },
  },
  {
    path: "/me/cases",
    name: "my-cases",
    component: () => import("../views/cases/CaseListView.vue"),
    meta: { requiresAuth: true },
  },
  {
    path: "/me/banned-items",
    name: "banned-items",
    component: () => import("../views/products/BannedScopeView.vue"),
    meta: { requiresAuth: true },
  },
  {
    path: "/trades/:tradeId",
    name: "trade-detail",
    component: () => import("../views/trades/TradeDetailView.vue"),
    meta: { requiresAuth: true },
  },
  {
    path: "/conversations",
    name: "conversations",
    component: () => import("../views/conversations/ConversationListView.vue"),
    meta: { requiresAuth: true },
  },
  {
    path: "/conversations/:kind/:conversationId",
    name: "conversation",
    component: () => import("../views/conversations/ConversationView.vue"),
    meta: { requiresAuth: true },
  },
  {
    path: "/cases/:caseId",
    name: "case-detail",
    component: () => import("../views/cases/CaseDetailView.vue"),
    meta: { requiresAuth: true },
  },
  {
    path: "/report",
    name: "report",
    component: () => import("../views/cases/ReportView.vue"),
    meta: { requiresAuth: true },
  },
  {
    path: "/:pathMatch(.*)*",
    name: "not-found",
    component: () => import("../views/NotFoundView.vue"),
    meta: { requiresAuth: true },
  },
];

export const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: (_to, _from, savedPosition) => savedPosition ?? { top: 0 },
});

router.beforeEach(async (to) => {
  await ensureSession();
  if (to.meta.requiresAuth && !session.isAuthenticated.value) {
    return { name: "login", query: { redirect: to.fullPath } };
  }
  if (to.meta.anonymous && session.isAuthenticated.value) {
    return { name: "home" };
  }
  return true;
});
