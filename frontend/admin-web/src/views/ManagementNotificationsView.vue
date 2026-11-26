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
import ContentState from "../../../shared/ContentState.vue";
import ErrorNotice from "../components/ErrorNotice.vue";
import LoadingBlock from "../components/LoadingBlock.vue";
import PaginationBar from "../components/PaginationBar.vue";

const props = defineProps<{ notificationId?: string }>();
const emit = defineEmits<{ unreadChanged: [] }>();
const pageSize = 10;
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
      total.value = result.total;
      unread.value = result.unread_count;
      const lastPage = Math.max(1, Math.ceil(result.total / pageSize));
      if (page.value > lastPage) {
        page.value = lastPage;
        return;
      }
      items.value = result.items;
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
    <header class="page-header">
      <p v-if="notificationId" class="page-header__eyebrow">通知</p>
      <div class="page-header__row">
        <h1>{{ notificationId ? (detail?.summary ?? "通知详情") : "通知" }}</h1>
        <div class="page-header__actions">
          <a v-if="notificationId" href="/notifications" data-admin-route class="btn btn--ghost">
            返回通知列表
          </a>
          <span v-else-if="unread" class="chip chip--active">{{ unread }} 条未读</span>
        </div>
      </div>
    </header>

    <div
      v-if="!notificationId"
      class="status-filter notification-filters"
      role="group"
      aria-label="按已读状态筛选"
    >
      <button
        v-for="(label, option) in filters"
        :key="option"
        type="button"
        class="status-filter__option"
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
        <div class="inline">
          <span class="chip">事项</span>
          <time class="muted" :datetime="detail.occurred_at">{{
            formatDateTime(detail.occurred_at)
          }}</time>
        </div>
        <dl v-if="detail.subject" class="context">
          <div>
            <dt>关联事项</dt>
            <dd class="break-anywhere">{{ detail.subject }}</dd>
          </div>
        </dl>
        <p v-if="detail.body" class="body pre-line break-anywhere">{{ detail.body }}</p>
        <div v-if="destination" class="inline">
          <a class="btn btn--primary" :href="destination.href" data-admin-route>{{
            destination.label
          }}</a>
        </div>
        <p v-if="detail.read_at" class="muted read-time">
          首次已读 <time :datetime="detail.read_at">{{ formatDateTime(detail.read_at) }}</time>
        </p>
        <ErrorNotice v-if="readError" :error="readError" @retry="retryRead" />
      </article>
    </template>
    <template v-else-if="!notificationId">
      <ContentState
        v-if="!items.length"
        kind="empty"
        :title="filter === 'unread' ? '没有未读通知' : '暂无通知'"
      />
      <ul v-else class="rows">
        <li v-for="item in items" :key="item.notification_id">
          <a
            class="row"
            :class="{ 'row--unread': !item.read_at }"
            :href="routeHref({ name: 'notifications', notificationId: item.notification_id })"
            data-admin-route
          >
            <span class="row__main">
              <span class="row__meta">
                <span class="row__type">事项</span>
                <strong class="row__summary break-anywhere">{{ item.summary }}</strong>
                <span v-if="!item.read_at" class="row__unread">未读</span>
                <time class="row__time muted" :datetime="item.occurred_at">{{
                  formatDateTime(item.occurred_at)
                }}</time>
              </span>
              <span v-if="item.subject" class="row__details muted break-anywhere">{{
                item.subject
              }}</span>
            </span>
            <span class="row__go" aria-hidden="true">›</span>
          </a>
        </li>
      </ul>
    </template>
    <PaginationBar
      v-if="!notificationId && !error"
      :page="page"
      :page-size="pageSize"
      :total="total"
      label="通知分页"
      show-single-page
      @change="page = $event"
    />
  </div>
</template>

<style scoped src="../../../shared/notification-page-header.css"></style>
<style scoped src="../../../shared/status-filter.css"></style>
<style scoped src="../../../shared/notification-list.css"></style>
<style scoped src="../../../shared/notification-detail.css"></style>
