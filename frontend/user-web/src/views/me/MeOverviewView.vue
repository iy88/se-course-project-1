<script setup lang="ts">
/*
 * "My" aggregation page (US-12) plus the personal to-do list (US-11).
 *
 * Counts and to-dos come from the shared aggregation endpoints so this page never
 * invents a second definition of "pending"; each entry links into the business
 * screen that owns the action.
 */
import { computed, onMounted } from "vue";
import { useRouter } from "vue-router";
import { listMyTodos, readOverview } from "../../api/aggregation";
import { logout } from "../../api/account";
import type { MyOverview, TodoItem } from "../../api/contracts";
import { useAsyncData } from "../../app/async";
import { formatRelative } from "../../app/format";
import { todoKindLabels } from "../../app/labels";
import { notify } from "../../app/toast";
import { clearSession, session } from "../../app/session";
import { resetBadges, refreshBadges } from "../../app/badges";
import AvatarBadge from "../../components/AvatarBadge.vue";
import EmptyState from "../../components/EmptyState.vue";
import ErrorNotice from "../../components/ErrorNotice.vue";
import LoadingBlock from "../../components/LoadingBlock.vue";

const router = useRouter();

const overview = useAsyncData<MyOverview>((signal) => readOverview(signal));
const todos = useAsyncData<{ items: TodoItem[]; total: number }>((signal) =>
  listMyTodos({ page: 1, page_size: 10 }, signal),
);

const productTotal = computed(() => overview.data.value?.products.total ?? 0);
const tradeTotal = computed(() => overview.data.value?.trades.total ?? 0);

onMounted(() => {
  void overview.run();
  void todos.run();
});

async function signOut(): Promise<void> {
  try {
    await logout();
  } catch {
    // A failed logout must still clear the local view; the session endpoint is
    // naturally idempotent, so the user can retry from the login screen.
  }
  clearSession();
  resetBadges();
  notify.info("已退出登录。");
  await router.replace({ name: "login" });
}

/** Route each to-do kind to the screen that can actually resolve it. */
function todoLink(item: TodoItem): { name: string; params?: Record<string, string> } {
  if (item.kind === "inquiry_response") {
    const caseId = String(item.source.case_id ?? "");
    return { name: "case-detail", params: { caseId } };
  }
  const tradeId = String(item.source.trade_id ?? "");
  return { name: "trade-detail", params: { tradeId } };
}

function refresh(): void {
  void overview.run();
  void todos.run();
  void refreshBadges();
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
        <p class="muted">{{ session.account.value?.email ?? "" }}</p>
      </div>
      <div class="me-head__actions">
        <RouterLink to="/me/profile" class="btn btn--small">编辑资料</RouterLink>
        <RouterLink to="/me/security" class="btn btn--small">账户安全</RouterLink>
      </div>
    </header>

    <LoadingBlock v-if="overview.isLoading.value" label="正在加载我的业务…" />
    <ErrorNotice
      v-else-if="overview.problem.value"
      :error="overview.error.value"
      @retry="refresh"
    />
    <template v-else-if="overview.data.value">
      <ul class="stat-grid">
        <li class="stat">
          <span class="stat__value">{{ productTotal }}</span>
          <span class="stat__label">我的商品</span>
          <RouterLink to="/me/products" class="stat__link">查看</RouterLink>
        </li>
        <li class="stat">
          <span class="stat__value">{{ tradeTotal }}</span>
          <span class="stat__label">我的交易</span>
          <RouterLink to="/me/trades" class="stat__link">查看</RouterLink>
        </li>
        <li class="stat">
          <span class="stat__value">{{ overview.data.value.reports.submitted }}</span>
          <span class="stat__label">我提交的事项</span>
          <RouterLink to="/me/cases" class="stat__link">查看</RouterLink>
        </li>
        <li class="stat">
          <span class="stat__value">{{ overview.data.value.evaluations.written }}</span>
          <span class="stat__label">我发表的评价</span>
          <span class="muted">收到 {{ overview.data.value.evaluations.received }} 条</span>
        </li>
      </ul>
    </template>

    <section class="card">
      <div class="card__head">
        <h2>待办</h2>
        <span class="chip">{{ overview.data.value?.todo_count ?? 0 }} 项待处理</span>
      </div>
      <LoadingBlock v-if="todos.isLoading.value" label="正在加载待办…" />
      <ErrorNotice v-else-if="todos.problem.value" :error="todos.error.value" @retry="todos.run" />
      <EmptyState
        v-else-if="!todos.data.value?.items.length"
        title="没有待处理的事项"
        description="新的请求、约定或问询会出现在这里。"
      />
      <ul v-else class="todo-list">
        <li v-for="item in todos.data.value.items" :key="item.todo_key">
          <RouterLink :to="todoLink(item)" class="todo">
            <span class="todo__kind">{{ todoKindLabels[item.kind] ?? item.kind }}</span>
            <span class="todo__summary">{{ item.summary }}</span>
            <span class="muted">{{ formatRelative(item.updated_at) }}</span>
          </RouterLink>
        </li>
      </ul>
    </section>

    <section class="card">
      <div class="card__head"><h2>更多</h2></div>
      <div class="link-grid">
        <RouterLink to="/me/notifications" class="link-tile">
          <span>通知</span>
          <span class="muted">审核结果、交易与事项提醒</span>
        </RouterLink>
        <RouterLink to="/conversations" class="link-tile">
          <span>消息</span>
          <span class="muted">私聊与逐笔交易会话</span>
        </RouterLink>
        <RouterLink to="/me/cases" class="link-tile">
          <span>我的事项</span>
          <span class="muted">举报进度、问询与申辩</span>
        </RouterLink>
        <RouterLink to="/me/banned-items" class="link-tile">
          <span>禁发范围</span>
          <span class="muted">发布前确认</span>
        </RouterLink>
      </div>
      <div class="inline signout">
        <button type="button" class="btn btn--ghost" @click="signOut">退出登录</button>
      </div>
    </section>
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

.stat-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(8rem, 1fr));
  gap: var(--space-3);
}

.stat {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
  padding: var(--space-3) var(--space-4);
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius);
}

.stat__value {
  font-size: 1.5rem;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.stat__label {
  font-size: 0.8125rem;
  color: var(--ink-soft);
}

.stat__link {
  font-size: 0.75rem;
}

.todo-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.todo {
  display: grid;
  gap: 0.125rem;
  padding: var(--space-3);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  color: var(--ink);
}

.todo:hover {
  border-color: var(--brand);
  text-decoration: none;
}

.todo__kind {
  font-size: 0.75rem;
  color: var(--brand-ink);
  font-weight: 600;
}

.todo__summary {
  font-size: 0.875rem;
}

.link-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(10rem, 1fr));
  gap: var(--space-3);
}

.link-tile {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
  padding: var(--space-3);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  color: var(--ink);
  font-size: 0.875rem;
}

.link-tile:hover {
  border-color: var(--brand);
  text-decoration: none;
}

.signout {
  margin-block-start: var(--space-4);
}
</style>
