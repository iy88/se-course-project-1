<script setup lang="ts">
/*
 * Application shell: brand row, primary navigation and the route outlet.
 *
 * Mobile uses a fixed bottom tab bar (thumb reach), wide screens use a left
 * navigation column so the content column keeps a comfortable measure.
 */
import { computed, watch } from "vue";
import { RouterLink, RouterView, useRoute } from "vue-router";
import { session } from "./app/session";
import { badges, refreshBadges } from "./app/badges";

import ToastHost from "./components/ToastHost.vue";
import AvatarBadge from "./components/AvatarBadge.vue";
import OfflineNotice from "./components/OfflineNotice.vue";

const route = useRoute();

const primaryNav = [
  { name: "home", label: "逛逛", badge: () => 0 },
  { name: "conversations", label: "消息", badge: () => badges.conversationUnread.value },
  { name: "notifications", label: "通知", badge: () => badges.notificationUnread.value },
  { name: "me", label: "我的", badge: () => 0 },
];

const isAuthScreen = computed(() => route.meta.anonymous === true);

watch(
  () => route.fullPath,
  () => {
    void refreshBadges();
  },
  { immediate: true },
);
</script>

<template>
  <OfflineNotice />
  <a class="skip-link" href="#main">跳到主要内容</a>
  <div class="shell" :class="{ 'shell--auth': isAuthScreen }">
    <header v-if="!isAuthScreen" class="shell__header">
      <RouterLink to="/" class="shell__brand">
        <span class="shell__logo" aria-hidden="true">二</span>
        <span class="shell__brand-text">校园二手交易</span>
      </RouterLink>
      <nav class="shell__nav" aria-label="主导航">
        <RouterLink
          v-for="item in primaryNav"
          :key="item.name"
          :to="{ name: item.name }"
          class="shell__nav-link"
        >
          {{ item.label }}
          <span v-if="item.badge() > 0" class="shell__badge">{{ item.badge() }}</span>
        </RouterLink>
      </nav>
      <RouterLink v-if="session.isAuthenticated.value" to="/me/settings" class="shell__account">
        <AvatarBadge
          :display-name="session.displayName.value"
          :url="session.avatarUrl.value"
          size="sm"
        />
        <span class="shell__account-name">{{ session.displayName.value }}</span>
      </RouterLink>
    </header>

    <main id="main" class="shell__main" :class="{ 'shell__main--auth': isAuthScreen }">
      <RouterView />
    </main>

    <nav v-if="!isAuthScreen" class="shell__tabbar" aria-label="底部导航">
      <RouterLink
        v-for="item in primaryNav"
        :key="item.name"
        :to="{ name: item.name }"
        class="shell__tab"
      >
        <span class="shell__tab-label">{{ item.label }}</span>
        <span v-if="item.badge() > 0" class="shell__badge">{{ item.badge() }}</span>
      </RouterLink>
    </nav>
  </div>
  <ToastHost />
</template>

<style scoped>
.shell {
  display: flex;
  flex-direction: column;
  min-block-size: 100dvh;
  max-inline-size: var(--shell-max);
  margin-inline: auto;
  padding-block-end: 4.25rem;
}

.shell--auth {
  padding-block-end: 0;
}

.shell__header {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-3) var(--space-4);
  background: var(--panel);
  border-block-end: 1px solid var(--line);
  position: sticky;
  inset-block-start: 0;
  z-index: 10;
}

.shell__brand {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--ink);
}

.shell__brand:hover {
  text-decoration: none;
}

.shell__logo {
  display: grid;
  place-items: center;
  inline-size: 1.75rem;
  block-size: 1.75rem;
  border-radius: var(--radius-sm);
  background: linear-gradient(135deg, #7fb79b, #2f6b4f);
  color: #0f221a;
  font-weight: 700;
  font-size: 0.75rem;
}

.shell__brand-text {
  font-weight: 650;
  font-size: 0.9375rem;
}

.shell__nav {
  display: none;
  gap: var(--space-1);
  margin-inline-start: var(--space-4);
}

.shell__nav-link {
  position: relative;
  padding: 0.3125rem 0.625rem;
  border-radius: var(--radius-sm);
  color: var(--ink-soft);
  font-size: 0.875rem;
}

.shell__nav-link.router-link-active {
  background: var(--brand-soft);
  color: var(--brand-ink);
  font-weight: 600;
}

.shell__nav-link:hover {
  text-decoration: none;
  background: #f4f8f5;
}

.shell__account {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  margin-inline-start: auto;
  color: var(--ink-soft);
  font-size: 0.8125rem;
}

.shell__account-name {
  display: none;
}

.shell__badge {
  display: inline-grid;
  place-items: center;
  min-inline-size: 1.125rem;
  block-size: 1.125rem;
  padding-inline: 0.25rem;
  border-radius: 999px;
  background: var(--danger);
  color: #fff;
  font-size: 0.625rem;
  font-weight: 700;
  margin-inline-start: 0.25rem;
}

.shell__main {
  flex: 1;
  padding: var(--space-4);
}

.shell__main--auth {
  display: grid;
  place-items: center;
}

.shell__tabbar {
  position: fixed;
  inset-block-end: 0;
  inset-inline: 0;
  z-index: 10;
  display: flex;
  justify-content: space-around;
  background: var(--panel);
  border-block-start: 1px solid var(--line);
  padding-block: 0.375rem;
  padding-block-end: max(0.375rem, env(safe-area-inset-bottom));
}

.shell__tab {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.125rem;
  flex: 1;
  padding: 0.375rem 0;
  color: var(--ink-faint);
  font-size: 0.75rem;
  min-block-size: var(--control-min-block);
  justify-content: center;
}

.shell__tab.router-link-active {
  color: var(--brand);
  font-weight: 600;
}

.shell__tab:hover {
  text-decoration: none;
}

@media (width >= 48rem) {
  .shell {
    padding-block-end: 0;
  }

  .shell__nav {
    display: flex;
  }

  .shell__account-name {
    display: inline;
  }

  .shell__tabbar {
    display: none;
  }

  .shell__main {
    padding: var(--space-6) var(--space-5);
  }
}
</style>
