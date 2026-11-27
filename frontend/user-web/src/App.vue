<script setup lang="ts">
/*
 * Application shell: brand row, primary navigation and the route outlet.
 *
 * Primary navigation sits at the bottom on mobile and in the header on desktop.
 */
import { computed, onBeforeUnmount, watch } from "vue";
import { RouterLink, RouterView, useRoute, useRouter } from "vue-router";
import BrandMark from "../../shared/BrandMark.vue";
import MobileBackButton from "../../shared/MobileBackButton.vue";
import PageFeedback from "../../shared/PageFeedback.vue";
import UiIcon from "../../shared/UiIcon.vue";
import { refreshSession, session } from "./app/session";
import { badges, refreshBadges, resetBadges } from "./app/badges";
import { backFallbackFor, hasBackEntry } from "./app/navigation";
import { refreshesNotificationList } from "./app/notification-events";
import {
  registerSnapshotReloader,
  resetRealtimeCursor,
  restartRealtime,
  subscribeRealtime,
} from "./app/realtime";

import { dismiss, toasts } from "./app/toast";
import AvatarBadge from "./components/AvatarBadge.vue";
import OfflineNotice from "./components/OfflineNotice.vue";

const route = useRoute();
const router = useRouter();

const primaryNav = [
  { name: "home", label: "逛逛", icon: "grid" },
  { name: "conversations", label: "消息", icon: "mail" },
  { name: "notifications", label: "通知", icon: "bell" },
  { name: "me", label: "我的", icon: "user" },
] as const;

const isAuthScreen = computed(() => route.meta.anonymous === true);
const hasSplitAuthLayout = computed(() => route.name === "login" || route.name === "register");
const activeSection = computed(() => {
  if (route.name === "conversations" || route.name === "conversation") return "conversations";
  if (route.path.startsWith("/me/notifications")) return "notifications";
  if (route.path === "/me" || route.path.startsWith("/me/")) return "me";
  if (route.path === "/" || route.path === "/search" || route.path.startsWith("/products/"))
    return "home";
  return null;
});
const isMessagesView = computed(() => activeSection.value === "conversations");
const backFallback = computed(() => backFallbackFor(route.meta, route.params));
const hasHistoryBack = computed(() => {
  // Reading fullPath refreshes the computed when navigation changes history state.
  void route.fullPath;
  return typeof window !== "undefined" && hasBackEntry(window.history.state);
});
const canGoBack = computed(() => backFallback.value !== null);
const backLabel = computed(() =>
  route.meta.backLabel ? `返回${route.meta.backLabel}` : "返回上一页",
);

function goBack(): void {
  if (hasHistoryBack.value) {
    router.back();
    return;
  }
  const fallback = backFallback.value;
  if (fallback) void router.push(fallback);
}

// Unread badges belong to the resync snapshot: after a `sync_reset` the client
// reloads every registered snapshot before resuming from the recorded head.
registerSnapshotReloader(() => refreshBadges());
registerSnapshotReloader(() => refreshSession());

let unsubscribeRealtime: (() => void) | null = null;
let badgeTimer: ReturnType<typeof setTimeout> | undefined;

function scheduleBadgeRefresh(): void {
  if (badgeTimer !== undefined) return;
  badgeTimer = setTimeout(() => {
    badgeTimer = undefined;
    void refreshBadges();
  }, 80);
}

// Realtime exists only while a session owns at least one subscription. The shell
// subscribes after authentication, and logout tears the subscription down so the
// transport closes even when a route component forgets to clean up.
watch(
  () => [session.isAuthenticated.value, session.accountId.value] as const,
  (current, previous) => {
    const [authenticated, accountId] = current;
    const [wasAuthenticated, previousAccountId] = previous ?? [false, null];
    if (!authenticated) {
      unsubscribeRealtime?.();
      unsubscribeRealtime = null;
      if (badgeTimer !== undefined) {
        clearTimeout(badgeTimer);
        badgeTimer = undefined;
      }
      resetRealtimeCursor();
      resetBadges();
      return;
    }
    const accountChanged =
      wasAuthenticated && previousAccountId !== null && accountId !== previousAccountId;
    if (accountChanged) {
      resetRealtimeCursor();
      resetBadges();
    }
    if (!unsubscribeRealtime) {
      unsubscribeRealtime = subscribeRealtime((frame) => {
        if (refreshesNotificationList(frame)) scheduleBadgeRefresh();
        if (frame.event_type === "notification_created") {
          void refreshSession().catch(() => {
            // Keep the last known restriction state until the next successful refresh.
          });
        }
      });
    }
    if (accountChanged) restartRealtime();
    void refreshBadges();
  },
  { immediate: true },
);

onBeforeUnmount(() => {
  unsubscribeRealtime?.();
  unsubscribeRealtime = null;
  if (badgeTimer !== undefined) clearTimeout(badgeTimer);
});

watch(
  () => route.fullPath,
  () => {
    void refreshBadges();
  },
  { immediate: true },
);
</script>

<template>
  <a class="skip-link" href="#main">跳到主要内容</a>
  <div class="shell" :class="{ 'shell--auth': isAuthScreen, 'shell--messages': isMessagesView }">
    <MobileBackButton
      v-if="isAuthScreen && canGoBack"
      class="shell__auth-back"
      :label="backLabel"
      @back="goBack"
    />
    <header v-if="!isAuthScreen" class="shell__header">
      <div class="shell__header-inner">
        <div class="shell__header-leading">
          <MobileBackButton
            v-if="canGoBack"
            class="shell__header-back"
            :label="backLabel"
            @back="goBack"
          />
          <RouterLink to="/" class="shell__brand" :class="{ 'shell__brand--with-back': canGoBack }">
            <BrandMark class="shell__logo" />
            <span class="shell__brand-text">校园二手交易</span>
          </RouterLink>
        </div>
        <nav class="shell__nav" aria-label="主导航">
          <RouterLink
            v-for="item in primaryNav"
            :key="item.name"
            :to="{ name: item.name }"
            class="shell__nav-link"
            :data-section="item.name"
            :aria-current="
              item.name === activeSection
                ? item.name === route.name
                  ? 'page'
                  : 'location'
                : undefined
            "
          >
            <span class="shell__nav-icon" aria-hidden="true">
              <UiIcon :name="item.icon" />
            </span>
            <span>{{ item.label }}</span>
            <span
              v-if="item.name === 'notifications' && badges.notificationUnread.value > 0"
              class="shell__badge"
            >
              <span class="visually-hidden">未读</span>{{ badges.notificationUnread.value }}
            </span>
          </RouterLink>
        </nav>
        <RouterLink
          v-if="session.isAuthenticated.value"
          to="/me"
          class="shell__account"
          aria-label="我的"
        >
          <AvatarBadge
            :display-name="session.displayName.value"
            :url="session.avatarUrl.value"
            size="sm"
          />
          <span class="shell__account-name">{{ session.displayName.value }}</span>
        </RouterLink>
      </div>
      <div v-if="session.account.value?.write_restricted" class="shell__restriction" role="status">
        <p>你的账户已封禁，部分操作受限。可在「我的事项」查看处理结果。</p>
      </div>
    </header>

    <OfflineNotice />
    <PageFeedback :messages="toasts" @dismiss="dismiss" />
    <main
      id="main"
      class="shell__main"
      :class="{ 'shell__main--auth': isAuthScreen, 'shell__main--split': hasSplitAuthLayout }"
    >
      <RouterView />
    </main>
  </div>
</template>

<style scoped>
.shell {
  --shell-gutter: 1rem;
  --tabbar-height: 4rem;
  display: flex;
  flex-direction: column;
  min-block-size: 100dvh;
  padding-block-end: calc(var(--tabbar-height) + env(safe-area-inset-bottom));
}

.shell--messages {
  block-size: 100dvh;
  overflow: hidden;
}

.shell--messages .shell__main {
  display: flex;
  min-block-size: 0;
  padding-block: var(--space-3);
}

.shell--auth {
  position: relative;
  padding-block-end: 0;
}

.shell__auth-back {
  position: absolute;
  inset-block-start: max(var(--space-3), env(safe-area-inset-top));
  inset-inline-start: var(--shell-gutter);
  z-index: 12;
  box-shadow: var(--shadow-soft);
}

.shell__header {
  position: sticky;
  inset-block-start: 0;
  z-index: 10;
  background: var(--panel);
  border-block-end: 1px solid var(--line);
}

.shell__restriction {
  color: var(--warn);
  background: var(--warn-soft);
}

.shell__restriction p {
  max-inline-size: var(--shell-max);
  margin: 0 auto;
  padding: var(--space-2) var(--shell-gutter);
}

.shell__header-inner {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--space-3);
  max-inline-size: var(--shell-max);
  min-block-size: 3.5rem;
  margin-inline: auto;
  padding-inline: var(--shell-gutter);
}

.shell__header-leading {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-inline-size: 0;
}

.shell__brand {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  justify-self: start;
  margin-inline-start: calc(-1 * var(--space-2));
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-sm);
  color: var(--ink);
  font-weight: 700;
  transition:
    background-color 150ms ease-out,
    color 150ms ease-out,
    scale 150ms ease-out;
}

.shell__brand:active {
  scale: 0.97;
}

.shell__logo {
  --brand-mark-size: 1.875rem;
}

.shell__brand-text {
  font-size: 0.9375rem;
}

.shell__nav {
  position: fixed;
  inset-inline: 0;
  inset-block-end: 0;
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  min-block-size: var(--tabbar-height);
  border-block-start: 1px solid var(--line);
  padding-block-end: env(safe-area-inset-bottom);
  background: var(--panel);
}

.shell__nav-link {
  --nav-icon-ink: var(--brand);
  --nav-icon-bg: var(--brand-soft);
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.125rem;
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-sm);
  color: var(--ink-faint);
  font-size: 0.75rem;
  transition:
    background-color 150ms ease-out,
    color 150ms ease-out,
    scale 150ms ease-out;
}

.shell__nav-link[data-section="notifications"] {
  --nav-icon-ink: var(--info);
  --nav-icon-bg: var(--info-soft);
}

.shell__nav-link[data-section="me"] {
  --nav-icon-ink: var(--accent);
  --nav-icon-bg: var(--accent-soft);
}

.shell__nav-link:focus-visible {
  outline-offset: -3px;
}

.shell__nav-icon {
  display: grid;
  place-items: center;
  inline-size: 2.75rem;
  block-size: 1.75rem;
  border-radius: 0.625rem;
  color: var(--nav-icon-ink);
}

.shell__nav-icon svg {
  inline-size: 1.25rem;
  block-size: 1.25rem;
}

.shell__nav-link:hover,
.shell__nav-link[aria-current] {
  color: var(--brand-ink);
}

.shell__nav-link[aria-current] {
  font-weight: 700;
}

.shell__nav-link[aria-current] .shell__nav-icon {
  background: var(--nav-icon-bg);
}

.shell__badge {
  display: inline-grid;
  place-items: center;
  min-inline-size: 1rem;
  block-size: 1rem;
  padding-inline: 0.25rem;
  border-radius: 999px;
  background: var(--danger);
  color: #fff;
  font-size: 0.625rem;
  font-weight: 700;
}

@media (width < 48rem) {
  .shell__brand--with-back {
    display: none;
  }

  .shell__badge {
    position: absolute;
    inset-block-start: 0.25rem;
    inset-inline-start: calc(50% + 0.55rem);
  }
}

.shell__account {
  display: flex;
  align-items: center;
  justify-self: end;
  gap: var(--space-2);
  min-block-size: var(--control-min-block);
  min-inline-size: var(--control-min-block);
  justify-content: center;
  margin-inline-end: calc(-1 * var(--space-2));
  padding-inline: var(--space-2);
  border-radius: var(--radius-sm);
  color: var(--ink-soft);
  font-size: 0.8125rem;
  transition:
    background-color 150ms ease-out,
    box-shadow 150ms ease-out,
    color 150ms ease-out,
    scale 150ms ease-out;
}

.shell__nav-link:active,
.shell__account:active {
  scale: 0.97;
}

.shell__account-name {
  display: none;
}

.shell__main {
  flex: 1;
  inline-size: 100%;
  max-inline-size: var(--shell-max);
  margin-inline: auto;
  padding: var(--space-5) var(--shell-gutter);
}

.shell__main--auth {
  display: grid;
  place-items: center;
  max-inline-size: none;
}

.shell__main.shell__main--split {
  display: flex;
  align-items: stretch;
  padding: 0;
}

@media (width >= 48rem) {
  .shell {
    --shell-gutter: 1.5rem;
    padding-block-end: 0;
  }

  .shell__header-inner {
    grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
    min-block-size: 4rem;
  }

  .shell__nav {
    position: static;
    align-self: stretch;
    display: flex;
    gap: var(--space-5);
    border: 0;
    padding: 0;
  }

  .shell__nav-link {
    flex-direction: row;
    gap: var(--space-1);
    padding-inline: var(--space-2);
    font-size: 0.875rem;
  }

  .shell__nav-link[aria-current]::after {
    content: "";
    position: absolute;
    inset-inline: var(--space-2);
    inset-block-end: 0;
    block-size: 2px;
    background: var(--nav-icon-ink);
  }

  .shell__nav-icon {
    inline-size: 1.625rem;
    block-size: 1.625rem;
    border-radius: 0.375rem;
  }

  .shell__nav-icon svg {
    inline-size: 1rem;
    block-size: 1rem;
  }

  .shell__account-name {
    display: inline;
    max-inline-size: 9rem;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .shell__main {
    padding-block-start: var(--space-6);
  }
}

@media (hover: hover) {
  .shell__brand:hover {
    background: var(--panel-soft);
    color: var(--brand-ink);
    text-decoration: none;
  }

  .shell__nav-link:hover {
    background: var(--panel-soft);
    color: var(--brand-ink);
    text-decoration: none;
  }

  .shell__nav-link:hover .shell__nav-icon {
    background: var(--nav-icon-bg);
  }

  .shell__account:hover {
    background: var(--panel-soft);
    box-shadow: inset 0 0 0 1px var(--line);
    color: var(--brand-ink);
    text-decoration: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .shell__brand,
  .shell__nav-link,
  .shell__account {
    transition: none;
  }

  .shell__brand:active,
  .shell__nav-link:active,
  .shell__account:active {
    scale: 1;
  }
}

@media (forced-colors: active) {
  .shell__nav-link[aria-current] .shell__nav-icon {
    outline: 1px solid Highlight;
  }

  .shell__nav-link[aria-current]::after {
    background: Highlight;
  }
}
</style>
