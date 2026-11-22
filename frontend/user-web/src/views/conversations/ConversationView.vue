<script setup lang="ts">
/*
 * One conversation branch.
 *
 * History is loaded backwards with the sequence cursor, and the read position is
 * advanced to the newest message the user can actually see once the page settles.
 * Realtime message frames for this branch trigger a refetch of the tail rather
 * than a local append, so sequence gaps after a reconnect heal themselves.
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { advanceReadProgress, listMessages, sendMessage } from "../../api/conversations";
import type { ConversationKind, ConversationMessage } from "../../api/contracts";
import { formatDateTime, formatRelative } from "../../app/format";
import { newIdempotencyKey } from "../../app/keys";
import { problemMessage } from "../../app/problems";
import { session } from "../../app/session";
import { subscribeRealtime } from "../../app/realtime";
import { refreshBadges } from "../../app/badges";
import { notify } from "../../app/toast";
import ErrorNotice from "../../components/ErrorNotice.vue";
import LoadingBlock from "../../components/LoadingBlock.vue";
import PageHeader from "../../components/PageHeader.vue";

const route = useRoute();
const kind = computed(() => String(route.params.kind ?? "chat") as ConversationKind);
const conversationId = computed(() => String(route.params.conversationId ?? ""));

const messages = ref<ConversationMessage[]>([]);
const loading = ref(false);
const loadingOlder = ref(false);
const error = ref<unknown>(null);
const draft = ref("");
const sending = ref(false);
const archived = ref(false);
const hasOlder = ref(false);
const oldestSeq = ref<number | null>(null);
const scroller = ref<HTMLElement | null>(null);
const readSeq = ref(0);

let pageSize = 30;
let unsubscribe: (() => void) | null = null;

const title = computed(() => {
  if (kind.value === "trade") return "交易会话";
  if (kind.value === "chat") return "私聊";
  return "事项会话";
});

async function loadTail(): Promise<void> {
  loading.value = true;
  error.value = null;
  try {
    const page = await listMessages(kind.value, conversationId.value, { limit: pageSize });
    messages.value = page.items;
    archived.value = page.branch_status === "archived";
    oldestSeq.value = page.next_before_seq ?? null;
    hasOlder.value = page.items.length >= pageSize;
    readSeq.value = page.items.length ? page.items[page.items.length - 1].seq : 0;
    await nextTick();
    scrollToBottom();
    await markRead();
  } catch (caught) {
    error.value = caught;
  } finally {
    loading.value = false;
  }
}

async function loadOlder(): Promise<void> {
  if (loadingOlder.value || oldestSeq.value === null) return;
  loadingOlder.value = true;
  try {
    const page = await listMessages(kind.value, conversationId.value, {
      before_seq: oldestSeq.value,
      limit: pageSize,
    });
    messages.value = [...page.items, ...messages.value];
    oldestSeq.value = page.next_before_seq ?? null;
    hasOlder.value = page.items.length >= pageSize;
  } catch (caught) {
    notify.error(problemMessage(caught));
  } finally {
    loadingOlder.value = false;
  }
}

async function markRead(): Promise<void> {
  if (!readSeq.value) return;
  try {
    const result = await advanceReadProgress(
      kind.value,
      conversationId.value,
      readSeq.value,
      newIdempotencyKey(),
    );
    readSeq.value = result.last_read_seq;
    void refreshBadges();
  } catch {
    // Read progress is monotonic and idempotent; the next visit retries it.
  }
}

async function send(): Promise<void> {
  const body = draft.value.trim();
  if (!body || sending.value) return;
  sending.value = true;
  try {
    await sendMessage(kind.value, conversationId.value, { body }, newIdempotencyKey());
    draft.value = "";
    await loadTail();
  } catch (caught) {
    notify.error(problemMessage(caught));
  } finally {
    sending.value = false;
  }
}

function scrollToBottom(): void {
  const element = scroller.value;
  if (element) element.scrollTop = element.scrollHeight;
}

function onRealtimeFrame(frame: { event_type: string; data: Record<string, unknown> }): void {
  if (frame.event_type !== "message_created" && frame.event_type !== "conversation_archived")
    return;
  if (String(frame.data.conversation_kind) !== kind.value) return;
  if (String(frame.data.conversation_id) !== conversationId.value) return;
  void loadTail();
}

watch(
  () => route.fullPath,
  () => {
    if (String(route.params.kind ?? "") === "") return;
    void loadTail();
  },
);

onMounted(() => {
  void loadTail();
  unsubscribe = subscribeRealtime(onRealtimeFrame);
});

onBeforeUnmount(() => {
  unsubscribe?.();
});
</script>

<template>
  <div class="stack stack--loose">
    <PageHeader
      eyebrow="消息"
      :title="title"
      :description="archived ? '该会话已归档，仅可查看历史消息。' : undefined"
    >
      <template #actions>
        <RouterLink to="/conversations" class="btn btn--ghost">返回消息列表</RouterLink>
      </template>
    </PageHeader>

    <LoadingBlock v-if="loading" label="正在加载消息…" />
    <ErrorNotice v-else-if="error" :error="error" @retry="loadTail" />
    <section v-else class="card chat">
      <div ref="scroller" class="chat__scroll">
        <div v-if="hasOlder" class="chat__older">
          <button type="button" class="btn btn--small" :disabled="loadingOlder" @click="loadOlder">
            {{ loadingOlder ? "加载中…" : "加载更早的消息" }}
          </button>
        </div>
        <p v-if="!messages.length" class="muted chat__empty">还没有消息，发送第一条吧。</p>
        <ul class="messages">
          <li
            v-for="message in messages"
            :key="message.message_id"
            class="message"
            :class="{
              'message--mine': message.sender.account_id === session.accountId.value,
              'message--system': message.sender.sender_kind === 'system',
            }"
          >
            <div class="message__meta">
              <span class="message__sender">{{ message.sender.display_name }}</span>
              <span class="muted" :title="formatDateTime(message.created_at)">
                {{ formatRelative(message.created_at) }}
              </span>
            </div>
            <p class="message__body pre-line break-anywhere">{{ message.body }}</p>
          </li>
        </ul>
      </div>

      <form v-if="!archived" class="chat__compose" @submit.prevent="send">
        <label class="visually-hidden" for="message-input">消息内容</label>
        <textarea
          id="message-input"
          v-model="draft"
          class="textarea"
          maxlength="2000"
          placeholder="输入消息，回车发送"
          @keydown.enter.exact.prevent="send"
        />
        <button type="submit" class="btn btn--primary" :disabled="sending || !draft.trim()">
          {{ sending ? "发送中…" : "发送" }}
        </button>
      </form>
      <p v-else class="banner banner--info chat__compose">
        该会话已归档，不能再发送消息；历史消息仍可查看。
      </p>
    </section>
  </div>
</template>

<style scoped>
.chat {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.chat__scroll {
  max-block-size: 60vh;
  overflow-y: auto;
  padding-inline-end: var(--space-1);
}

.chat__older {
  display: flex;
  justify-content: center;
  padding-block-end: var(--space-3);
}

.chat__empty {
  padding-block: var(--space-5);
  text-align: center;
}

.messages {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.message {
  max-inline-size: 85%;
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-sm);
  background: #f4f8f5;
  border: 1px solid var(--line);
}

.message--mine {
  margin-inline-start: auto;
  background: var(--brand-soft);
  border-color: #cbe3d4;
}

.message--system {
  max-inline-size: 100%;
  background: #f7f9f8;
  border-style: dashed;
  color: var(--ink-soft);
}

.message__meta {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
  margin-block-end: 0.125rem;
}

.message__sender {
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--ink-soft);
}

.message__body {
  font-size: 0.875rem;
}

.chat__compose {
  display: flex;
  gap: var(--space-2);
  align-items: flex-end;
  border-block-start: 1px solid var(--line);
  padding-block-start: var(--space-3);
}

.chat__compose .textarea {
  min-block-size: 3rem;
}
</style>
