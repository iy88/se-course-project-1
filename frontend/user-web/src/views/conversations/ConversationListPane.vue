<script setup lang="ts">
/*
 * Conversation branch list.
 *
 * One row per counterparty with each branch listed separately, so a private chat
 * and the per-transaction branches stay distinguishable. Case threads are reached
 * through the case screen and are not listed here. The pane works both as the
 * narrow-screen page body and as the left column of the wide layout.
 */
import { onBeforeUnmount, onMounted } from "vue";
import { useRoute, useRouter } from "vue-router";
import { listConversations } from "../../api/conversations";
import type { ConversationBranch, ConversationEntry, ConversationKind } from "../../api/contracts";
import { usePagedList } from "../../app/async";
import { conversationKey, rememberPeer } from "../../app/conversation-directory";
import { formatRelative, truncate } from "../../app/format";
import { registerSnapshotReloader, subscribeRealtime } from "../../app/realtime";
import AvatarBadge from "../../components/AvatarBadge.vue";
import EmptyState from "../../components/EmptyState.vue";
import ErrorNotice from "../../components/ErrorNotice.vue";
import LoadingBlock from "../../components/LoadingBlock.vue";
import PaginationBar from "../../components/PaginationBar.vue";

const route = useRoute();
const router = useRouter();

const list = usePagedList<ConversationEntry>((page, pageSize, signal) =>
  listConversations(page, pageSize, signal),
);

const activeKey = () => {
  const kind = String(route.params.kind ?? "");
  const id = String(route.params.conversationId ?? "");
  return kind && id ? conversationKey(kind, id) : "";
};

let requestedPage = 1;
let pendingPage: number | null = null;
let refreshTimer: ReturnType<typeof setTimeout> | undefined;
let loading: Promise<void> | undefined;
let unsubscribe: (() => void) | undefined;
let unregisterReloader: (() => void) | undefined;

async function loadPendingPages(): Promise<void> {
  try {
    while (pendingPage !== null) {
      const page = pendingPage;
      pendingPage = null;
      await list.load(page);
    }
  } finally {
    loading = undefined;
  }
}

function reload(page = requestedPage): Promise<void> {
  clearTimeout(refreshTimer);
  refreshTimer = undefined;
  requestedPage = page;
  pendingPage = page;
  loading ??= loadPendingPages();
  return loading;
}

function scheduleRefresh(): void {
  // Replay may deliver several changes before the next list query.
  refreshTimer ??= setTimeout(() => void reload(), 50);
}

onMounted(() => {
  void reload();
  unregisterReloader = registerSnapshotReloader(reload);
  unsubscribe = subscribeRealtime((frame) => {
    if (
      frame.event_type === "message_created" ||
      frame.event_type === "message_read" ||
      frame.event_type === "conversation_archived"
    ) {
      scheduleRefresh();
    }
  });
});

onBeforeUnmount(() => {
  unsubscribe?.();
  unregisterReloader?.();
  clearTimeout(refreshTimer);
  pendingPage = null;
  list.cancel();
});

function branchLabel(branch: ConversationBranch): string {
  if (branch.conversation_kind === "chat") return "私聊";
  if (branch.conversation_kind === "trade") return "交易会话";
  return "事项会话";
}

function open(branch: ConversationBranch): void {
  void router.push({
    name: "conversation",
    params: {
      kind: branch.conversation_kind satisfies ConversationKind,
      conversationId: branch.conversation_id,
    },
  });
}

function remember(entry: ConversationEntry, branch: ConversationBranch): void {
  rememberPeer(
    branch.conversation_kind,
    branch.conversation_id,
    entry.peer.display_name,
    entry.peer.account_id,
  );
}
</script>

<template>
  <section class="pane" aria-label="会话列表">
    <LoadingBlock v-if="list.isLoading.value && !list.items.value.length" label="正在加载会话…" />
    <ErrorNotice v-else-if="list.problem.value" :error="list.error.value" @retry="reload()" />
    <EmptyState
      v-else-if="list.isEmpty.value"
      title="还没有会话"
      description="在商品详情页咨询卖方，或接受购买请求后会建立对应会话。"
    >
      <RouterLink to="/" class="btn btn--primary">去逛逛</RouterLink>
    </EmptyState>
    <template v-else>
      <ul class="rows">
        <li v-for="entry in list.items.value" :key="entry.peer.account_id" class="entry">
          <header class="entry__head">
            <AvatarBadge
              :display-name="entry.peer.display_name"
              :url="entry.peer.avatar_url"
              size="md"
            />
            <span class="entry__name">{{ entry.peer.display_name }}</span>
          </header>
          <ul class="branches">
            <li
              v-for="branch in entry.branches"
              :key="`${branch.conversation_kind}-${branch.conversation_id}`"
            >
              <button
                type="button"
                class="branch"
                :class="{
                  'branch--active':
                    activeKey() ===
                    conversationKey(branch.conversation_kind, branch.conversation_id),
                }"
                @click="(remember(entry, branch), open(branch))"
              >
                <span class="branch__main">
                  <span class="inline">
                    <span class="chip">{{ branchLabel(branch) }}</span>
                    <span v-if="branch.archived_at" class="state state--neutral">已归档</span>
                  </span>
                  <span class="branch__preview muted clamp-1">
                    {{
                      branch.last_message_preview
                        ? truncate(branch.last_message_preview, 40)
                        : "暂无消息"
                    }}
                  </span>
                </span>
                <span class="branch__side">
                  <span v-if="branch.unread_count > 0" class="badge">{{
                    branch.unread_count
                  }}</span>
                  <span class="muted">{{ formatRelative(branch.last_message_at) }}</span>
                </span>
              </button>
            </li>
          </ul>
        </li>
      </ul>
      <PaginationBar
        :page="list.paging.page"
        :page-size="list.paging.pageSize"
        :total="list.paging.total"
        @change="reload"
      />
    </template>
  </section>
</template>

<style scoped>
.pane {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  min-inline-size: 0;
}

.rows {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.entry {
  padding: var(--space-3) var(--space-4);
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius);
}

.entry__head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-block-end: var(--space-2);
}

.entry__name {
  font-weight: 600;
  font-size: 0.875rem;
}

.branches {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.branch {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  inline-size: 100%;
  padding: var(--space-2);
  text-align: start;
  background: #fbfcfb;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  cursor: pointer;
}

.branch:hover {
  border-color: var(--brand);
}

.branch--active {
  background: var(--brand-soft);
  border-color: var(--brand);
}

.branch__main {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
  min-inline-size: 0;
}

.branch__preview {
  font-size: 0.8125rem;
}

.branch__side {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex: 0 0 auto;
}

.badge {
  display: inline-grid;
  place-items: center;
  min-inline-size: 1.25rem;
  block-size: 1.25rem;
  padding-inline: 0.25rem;
  border-radius: 999px;
  background: var(--danger);
  color: #fff;
  font-size: 0.6875rem;
  font-weight: 700;
}
</style>
