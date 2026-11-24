<script setup lang="ts">
/* Administration shell: identity gate, navigation and the active page. */
import { computed, onMounted } from "vue";
import MobileBackButton from "../../shared/MobileBackButton.vue";
import PageFeedback from "../../shared/PageFeedback.vue";
import UiIcon from "../../shared/UiIcon.vue";
import LoginView from "./views/LoginView.vue";
import BannedScopeView from "./views/BannedScopeView.vue";
import CategoriesView from "./views/CategoriesView.vue";
import ReviewDetailView from "./views/ReviewDetailView.vue";
import ReviewQueueView from "./views/ReviewQueueView.vue";
import ErrorNotice from "./components/ErrorNotice.vue";
import LoadingBlock from "./components/LoadingBlock.vue";
import { dismiss, toasts } from "./app/toast";
import { navigate, route } from "./app/router";
import { routeHref } from "./app/routes";
import { session } from "./app/session";
import "./styles/admin.css";

const navItems = [
  {
    key: "reviews",
    label: "商品审核",
    icon: "check",
    href: routeHref({ name: "reviews", ownership: "unclaimed" }),
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
] as const;

const page = computed(() => route.value.name);
const activeKey = computed(() => (page.value === "review" ? "reviews" : page.value));
const queueOwnership = computed(() =>
  route.value.name === "reviews" ? route.value.ownership : "unclaimed",
);
const reviewAuditId = computed(() => (route.value.name === "review" ? route.value.auditId : ""));
const canGoBack = computed(() => page.value !== "reviews");
const backLabel = computed(() => (page.value === "review" ? "返回我的认领" : "返回商品审核"));

onMounted(() => {
  void session.load();
});

async function signOut(): Promise<void> {
  await session.signOut();
}

function goBack(): void {
  navigate({
    name: "reviews",
    ownership: page.value === "review" ? "mine" : "unclaimed",
  });
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
            :class="{ 'admin-brand--with-back': canGoBack }"
            :href="routeHref({ name: 'reviews', ownership: 'unclaimed' })"
          >
            <span class="admin-brand__logo" aria-hidden="true">二</span>
            <span>
              校园二手交易
              <small>管理端</small>
            </span>
          </a>
        </div>
        <nav class="admin-nav" aria-label="管理导航">
          <a
            v-for="item in navItems"
            :key="item.key"
            :href="item.href"
            :aria-current="activeKey === item.key ? 'page' : undefined"
          >
            <UiIcon :name="item.icon" />
            {{ item.label }}
          </a>
        </nav>
        <div class="admin-account">
          <span class="admin-account__name">{{ session.displayName.value }}</span>
          <button type="button" class="btn btn--danger" @click="signOut">
            <UiIcon name="logout" />退出
          </button>
        </div>
      </div>
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
        <ReviewQueueView v-if="page === 'reviews'" :ownership="queueOwnership" />
        <ReviewDetailView v-else-if="page === 'review'" :audit-id="reviewAuditId" />
        <CategoriesView v-else-if="page === 'categories'" />
        <BannedScopeView v-else-if="page === 'banned'" />
      </template>
    </main>
  </div>
</template>
