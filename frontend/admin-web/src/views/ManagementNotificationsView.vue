<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from "vue";
import {
  listNotifications,
  markNotificationRead,
  readNotification,
  type ManagementNotification,
  type NotificationFilter,
} from "../api/notifications";
import { formatDateTime } from "../app/format";
import { IdempotencyKeys } from "../app/keys";
import { routeHref } from "../app/routes";
import ErrorNotice from "../components/ErrorNotice.vue";
import LoadingBlock from "../components/LoadingBlock.vue";
import PageHeader from "../components/PageHeader.vue";

const props = defineProps<{ notificationId?: string }>();
const emit = defineEmits<{ unreadChanged: [] }>();
const pageSize = 20;
const page = ref(1);
const total = ref(0);
const unread = ref(0);
const filter = ref<NotificationFilter>("all");
const filters = { all: "全部", unread: "未读", read: "已读" } as const;
const items = ref<ManagementNotification[]>([]);
const detail = ref<ManagementNotification>();
const loading = ref(false);
const error = ref<unknown>();
const readError = ref<unknown>();
const keys = new IdempotencyKeys();
let pending: AbortController | undefined;

const destination = computed(() => {
  const notice = detail.value;
  const source = notice?.source;
  if (!source) return undefined;
  switch (source.resource_type) {
    case "case":
      return {
        label: "查看事项",
        href: routeHref({
          name: "case",
          caseId: source.resource_id,
          ownership: "mine",
          kind: "all",
          keyword: "",
          anchor: notice.anchor,
        }),
      };
    case "product_audit":
      return {
        label: "查看审核",
        href: routeHref({ name: "review", auditId: source.resource_id }),
      };
    case "review_queue":
      return {
        label: "查看商品审核列表",
        href: routeHref({ name: "reviews", ownership: "unclaimed" }),
      };
    case "case_queue":
      return {
        label: "查看事项工作台",
        href: routeHref({ name: "cases", ownership: "unclaimed", kind: "all", keyword: "" }),
      };
    default:
      return undefined;
  }
});

async function markRead(item: ManagementNotification, signal: AbortSignal): Promise<void> {
  readError.value = undefined;
  const id = item.notification_id;
  try {
    const result = await markNotificationRead(id, keys.current(id), signal);
    if (signal.aborted) return;
    keys.rotate(id);
    detail.value = { ...item, read_at: result.read_at };
    emit("unreadChanged");
  } catch (caught) {
    if (!signal.aborted) readError.value = caught;
  }
}

async function load(): Promise<void> {
  pending?.abort();
  const controller = new AbortController();
  pending = controller;
  const { signal } = controller;
  const id = props.notificationId;
  loading.value = true;
  error.value = undefined;
  readError.value = undefined;
  try {
    if (id) {
      const item = await readNotification(id, signal);
      if (signal.aborted) return;
      detail.value = item;
      if (!item.read_at) void markRead(item, signal);
    } else {
      const result = await listNotifications(page.value, pageSize, filter.value, signal);
      if (signal.aborted) return;
      items.value = result.items;
      total.value = result.total;
      unread.value = result.unread_count;
    }
  } catch (caught) {
    if (!signal.aborted) error.value = caught;
  } finally {
    if (!signal.aborted) loading.value = false;
  }
}

function selectFilter(next: NotificationFilter): void {
  filter.value = next;
  page.value = 1;
}

function retryRead(): void {
  if (detail.value && pending) void markRead(detail.value, pending.signal);
}

watch([() => props.notificationId, page, filter], load, { immediate: true });
onUnmounted(() => pending?.abort());
</script>

<template>
  <div class="stack stack--loose">
    <PageHeader :title="notificationId ? '通知详情' : '通知'">
      <template #actions>
        <a v-if="notificationId" href="/notifications" data-admin-route class="btn btn--ghost"
          >返回通知列表</a
        >
        <template v-else>
          <span v-if="unread" class="chip">{{ unread }} 条未读</span>
          <button type="button" class="btn btn--ghost" :disabled="loading" @click="load">
            刷新
          </button>
        </template>
      </template>
    </PageHeader>

    <div v-if="!notificationId" class="inline" role="group" aria-label="按已读状态筛选">
      <button
        v-for="(label, option) in filters"
        :key="option"
        type="button"
        class="btn"
        :class="option === filter ? 'btn--primary' : 'btn--ghost'"
        :aria-pressed="option === filter"
        @click="selectFilter(option)"
      >
        {{ label }}
      </button>
    </div>

    <LoadingBlock v-if="loading" label="正在加载通知…" />
    <ErrorNotice v-else-if="error" :error="error" @retry="load" />
    <template v-else-if="notificationId && detail">
      <article class="card stack">
        <h2>{{ detail.summary }}</h2>
        <p v-if="detail.subject">{{ detail.subject }}</p>
        <time class="muted" :datetime="detail.occurred_at">{{
          formatDateTime(detail.occurred_at)
        }}</time>
        <p v-if="detail.body">{{ detail.body }}</p>
        <div v-if="destination" class="inline">
          <a class="btn btn--primary" :href="destination.href" data-admin-route>{{
            destination.label
          }}</a>
        </div>
        <p v-if="detail.read_at" class="muted">首次已读 {{ formatDateTime(detail.read_at) }}</p>
        <ErrorNotice v-if="readError" :error="readError" @retry="retryRead" />
      </article>
    </template>
    <template v-else-if="!notificationId">
      <p v-if="!items.length" class="card muted">
        {{ filter === "unread" ? "没有未读通知" : "暂无通知" }}
      </p>
      <ul v-else class="notification-list stack">
        <li v-for="item in items" :key="item.notification_id">
          <a
            class="notification-row card"
            :class="{ 'notification-row--unread': !item.read_at }"
            :href="routeHref({ name: 'notifications', notificationId: item.notification_id })"
            data-admin-route
          >
            <div class="stack stack--tight">
              <strong>{{ item.summary }}</strong>
              <span v-if="item.subject" class="muted">{{ item.subject }}</span>
            </div>
            <div class="inline">
              <span v-if="!item.read_at" class="chip">未读</span>
              <time class="muted" :datetime="item.occurred_at">{{
                formatDateTime(item.occurred_at)
              }}</time>
            </div>
          </a>
        </li>
      </ul>
      <nav v-if="total > pageSize" class="inline" aria-label="通知分页">
        <button type="button" class="btn" :disabled="page <= 1" @click="page--">上一页</button>
        <span>第 {{ page }} 页</span>
        <button type="button" class="btn" :disabled="page * pageSize >= total" @click="page++">
          下一页
        </button>
      </nav>
    </template>
  </div>
</template>

<style scoped>
.notification-list {
  padding: 0;
  list-style: none;
}

.notification-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: var(--space-2);
  color: var(--ink);
}

.notification-row--unread {
  border-inline-start: 0.25rem solid var(--brand-ink);
}
</style>
