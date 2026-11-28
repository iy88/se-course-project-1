<script setup lang="ts">
/* Administration shell: identity gate, navigation and the active page. */
import { storeToRefs } from "pinia";
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import BrandMark from "../../shared/BrandMark.vue";
import MobileBackButton from "../../shared/MobileBackButton.vue";
import PageFeedback from "../../shared/PageFeedback.vue";
import UiIcon from "../../shared/UiIcon.vue";
import LoginView from "./views/LoginView.vue";
import BannedScopeView from "./views/BannedScopeView.vue";
import CaseDetailView from "./views/CaseDetailView.vue";
import CaseQueueView from "./views/CaseQueueView.vue";
import CategoriesView from "./views/CategoriesView.vue";
import ReviewDetailView from "./views/ReviewDetailView.vue";
import ManagementNotificationsView from "./views/ManagementNotificationsView.vue";
import ManagementStatisticsView from "./views/ManagementStatisticsView.vue";
import ErrorNotice from "./components/ErrorNotice.vue";
import LoadingBlock from "./components/LoadingBlock.vue";
import { useToastStore } from "./app/toast";
import { navigate, route } from "./app/router";
import { parseLocation, reviewWorkbench, routeHref } from "./app/routes";
import { session } from "./app/session";
import { listNotifications } from "./api/notifications";
import "./styles/admin.css";

const navItems = [
  {
    key: "cases",
    label: "事项工作台",
    icon: "inbox",
    href: routeHref({ name: "cases", ownership: "unclaimed", kind: "all", keyword: "" }),
  },
  {
    key: "categories",
    label: "分类管理",
    icon: "grid",
    href: routeHref({ name: "categories" }),
  },
  {
    key: "banned",
    label: "禁发范围",
    icon: "file",
    href: routeHref({ name: "banned" }),
  },
  {
    key: "notifications",
    label: "通知",
    icon: "bell",
    href: routeHref({ name: "notifications" }),
  },
  {
    key: "statistics",
    label: "管理统计",
    icon: "file",
    href: routeHref({ name: "statistics" }),
  },
] as const;

const toastStore = useToastStore();
const { toasts } = storeToRefs(toastStore);
const { dismiss } = toastStore;

const page = computed(() => route.value.name);
const mobileNavOpen = ref(false);
const unreadNotifications = ref(0);
let unreadRequest: AbortController | undefined;
let unreadTimer: ReturnType<typeof setInterval> | undefined;

async function refreshUnread(): Promise<void> {
  unreadRequest?.abort();
  if (session.state.value !== "signed-in") {
    unreadNotifications.value = 0;
    return;
  }
  const controller = new AbortController();
  unreadRequest = controller;
  try {
    const result = await listNotifications(1, 1, "unread", controller.signal);
    if (!controller.signal.aborted) unreadNotifications.value = result.unread_count;
  } catch {
    // Keep the last count while the inbox is unavailable.
  }
}
const signOutDialog = ref<HTMLDialogElement | null>(null);
const activeKey = computed(() => {
  if (page.value === "review") return "cases";
  if (page.value === "notifications") return "返回通知列表";
  if (page.value === "case") return "cases";
  return page.value;
});
const reviewAuditId = computed(() => (route.value.name === "review" ? route.value.auditId : ""));
const workbench = computed(() =>
  route.value.name === "cases"
    ? route.value
    : { ownership: "unclaimed" as const, kind: "all" as const, keyword: "" },
);
const canGoBack = computed(
  () =>
    page.value !== "cases" &&
    (route.value.name !== "notifications" || Boolean(route.value.notificationId)),
);
const backLabel = computed(() => {
  if (page.value === "notifications") return "返回通知列表";
  if (page.value === "case") return "返回事项工作台";
  return "返回事项工作台";
});

onMounted(() => {
  void session.load();
  document.addEventListener("keydown", closeNavOnEscape);
  window.addEventListener("focus", refreshUnread);
  unreadTimer = setInterval(refreshUnread, 30_000);
});

onUnmounted(() => {
  document.removeEventListener("keydown", closeNavOnEscape);
  window.removeEventListener("focus", refreshUnread);
  clearInterval(unreadTimer);
  unreadRequest?.abort();
});

watch(
  () => route.value.name,
  () => {
    mobileNavOpen.value = false;
  },
);

watch(
  () => session.state.value,
  (state) => {
    if (state !== "signed-in") mobileNavOpen.value = false;
    void refreshUnread();
  },
);

async function signOut(): Promise<void> {
  await session.signOut();
}

function confirmSignOut(event: Event): void {
  const dialog = event.currentTarget as HTMLDialogElement;
  const confirmed = dialog.returnValue === "sign-out";
  dialog.returnValue = "";
  if (confirmed) void signOut();
}

function closeNavOnEscape(event: KeyboardEvent): void {
  if (event.key === "Escape" && !signOutDialog.value?.open) mobileNavOpen.value = false;
}

function goBack(): void {
  if (route.value.name === "notifications") {
    navigate({ name: "notifications" });
    return;
  }
  if (route.value.name === "case") {
    const { ownership, kind, keyword } = route.value;
    navigate({ name: "cases", ownership, kind, keyword });
    return;
  }
  navigate(page.value === "review" ? reviewWorkbench("mine") : parseLocation("/"));
}
</script>

<template>
  <div class="admin-shell">
    <header v-if="session.state.value === 'signed-in'" class="admin-header">
      <div class="admin-header__inner">
        <div class="admin-header__leading">
          <MobileBackButton
            v-if="canGoBack"
            class="admin-header__back"
            :label="backLabel"
            @back="goBack"
          />
          <a
            class="admin-brand"
            data-admin-route
            :class="{ 'admin-brand--with-back': canGoBack }"
            :href="navItems[0].href"
          >
            <BrandMark />
            <span>
              校园二手交易
              <small>管理端</small>
            </span>
          </a>
        </div>
        <nav
          id="admin-navigation"
          class="admin-nav"
          :class="{ 'admin-nav--open': mobileNavOpen }"
          aria-label="管理导航"
        >
          <a
            v-for="item in navItems"
            :key="item.key"
            :href="item.href"
            data-admin-route
            :aria-current="activeKey === item.key ? 'page' : undefined"
            @click="mobileNavOpen = false"
          >
            <UiIcon :name="item.icon" />
            {{ item.label }}
            <span
              v-if="item.key === 'notifications' && unreadNotifications"
              class="chip"
              :aria-label="`${unreadNotifications} 条未读`"
              >{{ unreadNotifications > 99 ? "99+" : unreadNotifications }}</span
            >
          </a>
          <button
            type="button"
            class="btn btn--danger admin-nav__sign-out"
            @click="signOutDialog?.showModal()"
          >
            <UiIcon name="logout" />退出
          </button>
        </nav>
        <div class="admin-account">
          <span class="admin-account__name">{{ session.displayName.value }}</span>
          <button
            type="button"
            class="btn btn--ghost admin-menu-toggle"
            aria-controls="admin-navigation"
            :aria-expanded="mobileNavOpen"
            :aria-label="mobileNavOpen ? '关闭管理导航' : '打开管理导航'"
            @click="mobileNavOpen = !mobileNavOpen"
          >
            <UiIcon :name="mobileNavOpen ? 'close' : 'menu'" />
            <span>{{ mobileNavOpen ? "关闭" : "菜单" }}</span>
          </button>
          <button
            type="button"
            class="btn btn--danger admin-account__sign-out"
            @click="signOutDialog?.showModal()"
          >
            <UiIcon name="logout" />退出
          </button>
        </div>
      </div>
      <dialog
        ref="signOutDialog"
        class="card admin-sign-out-dialog"
        aria-labelledby="admin-sign-out-title"
        @close="confirmSignOut"
      >
        <form method="dialog" class="stack">
          <h1 id="admin-sign-out-title">确认退出管理端？</h1>
          <div class="inline admin-sign-out-dialog__actions">
            <button type="submit" value="cancel" class="btn btn--ghost" autofocus>取消</button>
            <button type="submit" value="sign-out" class="btn btn--danger">确认退出</button>
          </div>
        </form>
      </dialog>
    </header>

    <PageFeedback :messages="toasts" @dismiss="dismiss" />
    <main class="admin-main" :class="{ 'admin-main--login': session.state.value === 'signed-out' }">
      <LoadingBlock v-if="session.state.value === 'loading'" label="正在确认管理身份…" />
      <ErrorNotice
        v-else-if="session.state.value === 'failed'"
        :error="session.failure.value"
        @retry="session.load"
      />
      <LoginView v-else-if="session.state.value === 'signed-out'" />
      <section v-else-if="session.state.value === 'forbidden'" class="card forbidden">
        <h1>需要平台管理权限</h1>
        <p class="muted">
          当前账号
          <strong>{{ session.identity.value?.account.email }}</strong>
          不是平台管理员。请退出后使用管理员账号登录。
        </p>
        <button type="button" class="btn btn--primary" @click="signOut">退出登录</button>
      </section>
      <template v-else>
        <CaseQueueView
          v-if="page === 'cases'"
          :ownership="workbench.ownership"
          :kind="workbench.kind"
          :keyword="workbench.keyword"
        />
        <CaseDetailView
          v-else-if="route.name === 'case'"
          :key="route.caseId"
          :case-id="route.caseId"
          :anchor="route.anchor"
          :back-href="
            routeHref({
              name: 'cases',
              ownership: route.ownership,
              kind: route.kind,
              keyword: route.keyword,
            })
          "
        />
        <ReviewDetailView v-else-if="page === 'review'" :audit-id="reviewAuditId" />
        <CategoriesView v-else-if="page === 'categories'" />
        <BannedScopeView v-else-if="page === 'banned'" />
        <ManagementNotificationsView
          v-else-if="route.name === 'notifications'"
          :notification-id="route.notificationId"
          @unread-changed="refreshUnread"
        />
        <ManagementStatisticsView v-else-if="page === 'statistics'" />
      </template>
    </main>
  </div>
</template>
