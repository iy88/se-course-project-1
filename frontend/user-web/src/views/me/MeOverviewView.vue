<script setup lang="ts">
import { useRouter } from "vue-router";
import { ref } from "vue";
import UiIcon from "../../../../shared/UiIcon.vue";
import { logout } from "../../api/account";
import { notify } from "../../app/toast";
import { problemMessage } from "../../app/problems";
import { clearSession, session } from "../../app/session";
import { resetBadges } from "../../app/badges";
import AvatarBadge from "../../components/AvatarBadge.vue";

const router = useRouter();
const signOutDialog = ref<HTMLDialogElement | null>(null);
const signingOut = ref(false);
const signOutError = ref("");

const links = [
  { to: "/me/products", title: "我的商品", description: "管理发布内容与审核状态", icon: "box" },
  { to: "/me/favorites", title: "我的收藏", description: "查看已收藏的商品", icon: "bookmark" },
] as const;

const rules = [
  {
    to: "/me/banned-items",
    title: "禁发范围",
    description: "发布前查阅不可交易的内容",
    icon: "file",
  },
] as const;

async function signOut(): Promise<void> {
  if (signingOut.value) return;
  signingOut.value = true;
  signOutError.value = "";
  try {
    await logout();
    signOutDialog.value?.close();
    clearSession();
    resetBadges();
    notify.info("已退出登录。");
    await router.replace({ name: "login" });
  } catch (error) {
    signOutError.value = problemMessage(error);
  } finally {
    signingOut.value = false;
  }
}

function requestSignOut(): void {
  signOutError.value = "";
  signOutDialog.value?.showModal();
}
</script>

<template>
  <div class="stack stack--loose">
    <header class="me-head card">
      <AvatarBadge
        :display-name="session.displayName.value"
        :url="session.avatarUrl.value"
        size="lg"
      />
      <div class="me-head__info">
        <h1>{{ session.displayName.value || "未登录" }}</h1>
        <p class="muted break-anywhere">{{ session.account.value?.email ?? "" }}</p>
      </div>
      <div class="me-head__actions">
        <RouterLink to="/me/settings" class="btn"><UiIcon name="settings" />账户设置</RouterLink>
        <button type="button" class="btn btn--danger" @click="requestSignOut">
          <UiIcon name="logout" />退出登录
        </button>
      </div>
    </header>

    <div class="me-sections">
      <section class="card me-section" aria-labelledby="my-market-title">
        <h2 id="my-market-title">商品</h2>
        <RouterLink v-for="link in links" :key="link.to" :to="link.to" class="me-section__link">
          <span class="me-section__icon" aria-hidden="true">
            <UiIcon :name="link.icon" />
          </span>
          <span class="me-section__copy">
            <span class="me-section__label">{{ link.title }}</span>
            <span class="me-section__description">{{ link.description }}</span>
          </span>
          <span class="me-section__chevron" aria-hidden="true">
            <UiIcon name="chevron-right" />
          </span>
        </RouterLink>
      </section>
      <section class="card me-section" aria-labelledby="listing-rules-title">
        <h2 id="listing-rules-title">发布规则</h2>
        <RouterLink v-for="link in rules" :key="link.to" :to="link.to" class="me-section__link">
          <span class="me-section__icon" aria-hidden="true">
            <UiIcon :name="link.icon" />
          </span>
          <span class="me-section__copy">
            <span class="me-section__label">{{ link.title }}</span>
            <span class="me-section__description">{{ link.description }}</span>
          </span>
          <span class="me-section__chevron" aria-hidden="true">
            <UiIcon name="chevron-right" />
          </span>
        </RouterLink>
      </section>
    </div>

    <dialog
      ref="signOutDialog"
      class="signout-dialog"
      aria-labelledby="signout-title"
      @cancel="signingOut && $event.preventDefault()"
    >
      <h2 id="signout-title">退出登录？</h2>
      <p v-if="signOutError" class="field__error" role="alert">{{ signOutError }}</p>
      <form method="dialog" class="signout-dialog__actions">
        <button class="btn" autofocus :disabled="signingOut">取消</button>
        <button type="button" class="btn btn--danger" :disabled="signingOut" @click="signOut">
          {{ signingOut ? "正在退出…" : "确认退出" }}
        </button>
      </form>
    </dialog>
  </div>
</template>

<style scoped>
.me-head {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  flex-wrap: wrap;
}

.me-head__info {
  flex: 1;
  min-inline-size: 8rem;
}

.me-head__info h1 {
  font-size: 1.25rem;
}

.me-head__actions {
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.me-head__actions .btn {
  padding-inline: var(--space-4);
}

.signout-dialog {
  inline-size: min(24rem, calc(100% - 2rem));
  max-block-size: calc(100dvh - 2rem);
  padding: var(--space-5);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--panel);
  color: var(--ink);
  overscroll-behavior: contain;
}

.signout-dialog::backdrop {
  background: rgb(24 39 32 / 36%);
  overflow: hidden;
  overscroll-behavior: contain;
}

.signout-dialog h2 {
  font-size: 1.125rem;
}

.signout-dialog .field__error {
  margin-block-start: var(--space-3);
}

.signout-dialog__actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
  margin-block-start: var(--space-5);
}

.me-sections {
  display: grid;
  gap: var(--space-3);
  align-items: start;
}

.me-section h2 {
  color: var(--ink-soft);
  font-size: 0.875rem;
}

.me-section {
  display: grid;
  gap: var(--space-2);
}

.me-section__link {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--space-3);
  min-block-size: 4rem;
  padding: var(--space-2);
  border-radius: var(--radius-sm);
  box-shadow: inset 0 0 0 1px transparent;
  color: var(--ink);
  cursor: pointer;
  transition:
    background-color 150ms ease-out,
    box-shadow 150ms ease-out,
    scale 150ms ease-out;
}

.me-section__link:active {
  background: var(--brand-soft);
  scale: 0.985;
}

.me-section__icon {
  display: grid;
  place-items: center;
  inline-size: 2rem;
  block-size: 2rem;
  border-radius: var(--radius-sm);
  background: var(--brand-soft);
  color: var(--brand-ink);
  transition:
    background-color 150ms ease-out,
    scale 150ms ease-out;
}

.me-section__link[href="/me/favorites"] .me-section__icon {
  background: var(--accent-soft);
  color: var(--accent);
}

.me-section__link[href="/me/banned-items"] .me-section__icon {
  background: var(--info-soft);
  color: var(--info);
}

.me-section__icon svg {
  inline-size: 1.125rem;
  block-size: 1.125rem;
}

.me-section__copy {
  display: grid;
  gap: 0.0625rem;
  min-inline-size: 0;
}

.me-section__label {
  font-weight: 650;
}

.me-section__description {
  color: var(--ink-soft);
  font-size: 0.75rem;
  line-height: 1.45;
}

.me-section__chevron {
  display: grid;
  place-items: center;
  color: var(--ink-faint);
  transition:
    color 150ms ease-out,
    translate 150ms ease-out;
}

.me-section__chevron svg {
  inline-size: 1rem;
  block-size: 1rem;
}

@media (width >= 48rem) {
  .me-sections {
    grid-template-columns: minmax(0, 3fr) minmax(0, 2fr);
  }
}

@media (hover: hover) {
  .me-section__link:hover {
    background: var(--brand-soft);
    box-shadow: inset 0 0 0 1px var(--line-strong);
    color: var(--ink);
    text-decoration: none;
  }

  .me-section__link:hover .me-section__icon {
    background: var(--panel);
    scale: 1.04;
  }

  .me-section__link:hover .me-section__chevron {
    color: var(--brand);
    translate: 2px 0;
  }
}

@media (prefers-reduced-motion: reduce) {
  .me-section__link,
  .me-section__icon,
  .me-section__chevron {
    transition: none;
  }

  .me-section__link:active {
    scale: 1;
  }

  .me-section__link:hover .me-section__icon {
    scale: 1;
  }

  .me-section__link:hover .me-section__chevron {
    translate: none;
  }
}
</style>
