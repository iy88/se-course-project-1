<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import UiIcon from "../../../../shared/UiIcon.vue";
import { logout } from "../../api/account";
import { readOverview } from "../../api/aggregation";
import type { MyOverview } from "../../api/contracts";
import { useAsyncData } from "../../app/async";
import { formatDateTime } from "../../app/format";
import { notify } from "../../app/toast";
import { problemMessage } from "../../app/problems";
import { clearSession, session } from "../../app/session";
import { resetBadges } from "../../app/badges";
import { resetRealtimeCursor } from "../../app/realtime";
import AvatarBadge from "../../components/AvatarBadge.vue";
import ErrorNotice from "../../components/ErrorNotice.vue";
import LoadingBlock from "../../components/LoadingBlock.vue";

const router = useRouter();
const signOutDialog = ref<HTMLDialogElement | null>(null);
const signingOut = ref(false);
const signOutError = ref("");
const overview = useAsyncData<MyOverview>((signal) => readOverview(signal));

const links = [
  {
    to: "/me/todos",
    title: "我的待办",
    description: "处理交易请求、约定、完成、取消与管理问询",
    icon: "inbox",
  },
  { to: "/me/products", title: "我的商品", description: "管理发布内容与审核状态", icon: "box" },
  { to: "/me/favorites", title: "我的收藏", description: "查看已收藏的商品", icon: "bookmark" },
  { to: "/me/trades", title: "我的交易", description: "查看购买与出售记录", icon: "file" },
  { to: "/me/reviews", title: "我的评价", description: "查看写出的和收到的评价", icon: "check" },
  { to: "/conversations", title: "我的会话", description: "查看私聊与交易消息", icon: "mail" },
  { to: "/me/cases", title: "我的事项", description: "查看举报、处理进度与结果", icon: "file" },
] as const;

onMounted(() => {
  void overview.run();
});

async function signOut(): Promise<void> {
  if (signingOut.value) return;
  signingOut.value = true;
  signOutError.value = "";
  try {
    await logout();
    signOutDialog.value?.close();
    clearSession();
    resetRealtimeCursor();
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

    <section class="card overview" aria-labelledby="overview-title">
      <div class="card__head">
        <h2 id="overview-title">账户概览</h2>
        <button
          type="button"
          class="btn btn--small btn--ghost"
          :disabled="overview.isLoading.value"
          @click="overview.run"
        >
          {{ overview.isLoading.value ? "刷新中…" : "刷新" }}
        </button>
      </div>
      <LoadingBlock v-if="overview.isLoading.value && !overview.data.value" label="正在汇总…" />
      <ErrorNotice
        v-else-if="overview.problem.value"
        :error="overview.error.value"
        @retry="overview.run"
      />
      <ul v-else-if="overview.data.value" class="overview__stats">
        <li>
          <RouterLink to="/me/products" class="overview__stat">
            <span class="overview__value">{{ overview.data.value.products.total }}</span>
            <span class="overview__label">商品</span>
            <span class="muted overview__detail">
              在售 {{ overview.data.value.products.by_state.public ?? 0 }}
            </span>
          </RouterLink>
        </li>
        <li>
          <RouterLink to="/me/trades" class="overview__stat">
            <span class="overview__value">{{ overview.data.value.trades.total }}</span>
            <span class="overview__label">交易</span>
            <span class="muted overview__detail">
              买入 {{ overview.data.value.trades.buying }} · 卖出
              {{ overview.data.value.trades.selling }}
            </span>
          </RouterLink>
        </li>
        <li>
          <RouterLink to="/me/favorites" class="overview__stat">
            <span class="overview__value">{{ overview.data.value.favorites.total }}</span>
            <span class="overview__label">收藏</span>
            <span class="muted overview__detail">
              有效 {{ overview.data.value.favorites.valid }} · 失效
              {{ overview.data.value.favorites.invalid }}
            </span>
          </RouterLink>
        </li>
        <li>
          <RouterLink to="/me/reviews" class="overview__stat">
            <span class="overview__value">{{ overview.data.value.evaluations.received }}</span>
            <span class="overview__label">收到的评价</span>
            <span class="muted overview__detail">
              已写 {{ overview.data.value.evaluations.written }}
            </span>
          </RouterLink>
        </li>
        <li>
          <RouterLink to="/me/todos" class="overview__stat overview__stat--todo">
            <span class="overview__value">{{ overview.data.value.todo_count }}</span>
            <span class="overview__label">我的待办</span>
            <span class="muted overview__detail">逐条在对应详情完成</span>
          </RouterLink>
        </li>
      </ul>
      <p v-if="overview.data.value" class="muted overview__asof">
        统计时点：{{ formatDateTime(overview.data.value.as_of) }}
      </p>
    </section>

    <aside class="publish-guide" aria-labelledby="listing-rules-title">
      <span class="publish-guide__icon" aria-hidden="true">
        <UiIcon name="file" />
      </span>
      <div class="publish-guide__copy">
        <span class="publish-guide__eyebrow">发布前提示</span>
        <h2 id="listing-rules-title">先确认禁发范围，再发布商品</h2>
        <p>法规禁止、危险管制、药品医疗等不可交易内容会在这里统一维护。</p>
      </div>
      <RouterLink to="/me/banned-items" class="btn publish-guide__action">
        查看禁发范围
        <UiIcon name="chevron-right" />
      </RouterLink>
    </aside>

    <section class="card me-section" aria-labelledby="my-market-title">
      <h2 id="my-market-title">我的业务</h2>
      <div class="me-section__grid">
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
      </div>
    </section>

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

.publish-guide {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: start;
  gap: var(--space-3) var(--space-4);
  padding: var(--space-4);
  border: 1px solid #cfe0ee;
  border-radius: var(--radius);
  background: var(--info-soft);
  box-shadow: var(--shadow-soft);
}

.publish-guide__icon {
  display: grid;
  place-items: center;
  inline-size: 2.5rem;
  block-size: 2.5rem;
  border-radius: var(--radius-sm);
  background: var(--panel);
  box-shadow: inset 0 0 0 1px #cfe0ee;
  color: var(--info);
}

.publish-guide__icon svg {
  inline-size: 1.25rem;
  block-size: 1.25rem;
}

.publish-guide__copy {
  display: grid;
  gap: 0.125rem;
  min-inline-size: 0;
}

.publish-guide__eyebrow {
  color: var(--info);
  font-size: 0.71875rem;
  font-weight: 700;
  letter-spacing: 0.08em;
}

.publish-guide__copy h2 {
  font-size: 1rem;
}

.publish-guide__copy p {
  max-inline-size: 46rem;
  color: var(--ink-soft);
  font-size: 0.8125rem;
  line-height: 1.55;
}

.publish-guide__action {
  grid-column: 1 / -1;
  justify-self: start;
  background: var(--panel);
  white-space: nowrap;
}

.overview {
  display: grid;
  gap: var(--space-3);
}

.overview__stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(9.5rem, 1fr));
  gap: var(--space-2);
  margin: 0;
  padding: 0;
  list-style: none;
}

.overview__stat {
  display: grid;
  gap: 0.0625rem;
  min-block-size: 100%;
  padding: var(--space-3);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--panel-soft);
  color: var(--ink);
  text-decoration: none;
}

.overview__stat--todo {
  border-color: var(--brand);
  background: var(--brand-soft);
}

.overview__value {
  color: var(--accent);
  font-size: 1.5rem;
  font-weight: 750;
  line-height: 1.1;
  font-variant-numeric: tabular-nums;
}

.overview__label {
  font-size: 0.8125rem;
  font-weight: 650;
}

.overview__detail {
  font-size: 0.75rem;
  line-height: 1.45;
}

.overview__asof {
  font-size: 0.75rem;
}

@media (hover: hover) {
  .overview__stat:hover {
    border-color: var(--brand);
    background: var(--brand-soft);
    text-decoration: none;
  }
}

.me-section h2 {
  color: var(--ink-soft);
  font-size: 0.875rem;
}

.me-section {
  display: grid;
  gap: var(--space-3);
  container-type: inline-size;
}

.me-section__grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--space-2);
}

.me-section__link {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--space-3);
  min-inline-size: 0;
  min-block-size: 4rem;
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-sm);
  background: var(--panel-soft);
  box-shadow: inset 0 0 0 1px var(--line);
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

@container (inline-size >= 46rem) {
  .me-section__grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--space-2) var(--space-3);
  }

  .me-section__grid > :last-child:nth-child(odd) {
    grid-column: 1 / -1;
  }
}

@media (width >= 48rem) {
  .publish-guide {
    grid-template-columns: auto minmax(0, 1fr) auto;
    align-items: center;
    padding: var(--space-4) var(--space-5);
  }

  .publish-guide__action {
    grid-column: auto;
    justify-self: end;
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
