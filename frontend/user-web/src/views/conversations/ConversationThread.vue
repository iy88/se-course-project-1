<script setup lang="ts">
/*
 * One conversation branch.
 *
 * History loads backwards with the sequence cursor and the read position advances
 * to the newest visible message. Realtime frames load messages after the current
 * sequence, including gaps left by a reconnect.
 *
 * Layout follows the message-screen rules: my messages sit on the right, the peer's
 * on the left, system events are centred, consecutive messages from the same sender
 * in the same minute merge, and days are separated. Enter sends unless the IME is
 * composing; Shift+Enter inserts a line break. An archived branch keeps the thread
 * visible and replaces the composer in place with a read-only notice.
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { advanceReadProgress, listMessages, sendMessage } from "../../api/conversations";
import { getTrade } from "../../api/trades";
import type { ConversationKind, ConversationMessage } from "../../api/contracts";
import { shouldSendOnEnter } from "../../app/composer";
import { peerAccountId, peerName, rememberPeer } from "../../app/conversation-directory";
import { buildConversationRows, type ConversationRow } from "../../app/conversation-rows";
import { formatDateTime, formatRelative } from "../../app/format";
import { newIdempotencyKey } from "../../app/keys";
import { problemMessage } from "../../app/problems";
import { realtimeState, registerSnapshotReloader, subscribeRealtime } from "../../app/realtime";
import { session } from "../../app/session";
import { notify } from "../../app/toast";
import ErrorNotice from "../../components/ErrorNotice.vue";
import LoadingBlock from "../../components/LoadingBlock.vue";
import StartChatButton from "../../components/interaction/StartChatButton.vue";

const route = useRoute();
const router = useRouter();
const kind = computed(() => String(route.params.kind ?? "chat") as ConversationKind);
const conversationId = computed(() => String(route.params.conversationId ?? ""));

const messages = ref<ConversationMessage[]>([]);
const loading = ref(false);
const loadingOlder = ref(false);
const error = ref<unknown>(null);
const draft = ref("");
const sending = ref(false);
const archived = ref(false);
const tradeId = ref<string>();
const tradePeerId = ref<string | null>(peerAccountId(kind.value, conversationId.value));
const hasOlder = ref(false);
const oldestSeq = ref<number | null>(null);
const scroller = ref<HTMLElement | null>(null);
const composer = ref<HTMLTextAreaElement | null>(null);
const loaded = ref(false);
const abort = new AbortController();
const pageSize = 30;
let refreshPending = false;
let refreshInFlight: Promise<void> | undefined;
let acknowledgedSeq = 0;
let updatingRead = false;
let unsubscribe: (() => void) | null = null;
let unregisterReloader: (() => void) | null = null;
/** True while an IME composition session owns the Enter key. */
let composing = false;

const title = computed(() => {
  if (kind.value === "trade") return "交易会话";
  if (kind.value === "chat") return "私聊";
  return "事项会话";
});

const heading = computed(() => peerName(kind.value, conversationId.value) ?? title.value);

const latestSeq = computed(() => messages.value[messages.value.length - 1]?.seq);

const rows = computed<ConversationRow[]>(() =>
  buildConversationRows(messages.value, { viewerAccountId: session.accountId.value }),
);

let peerRequestFor: string | null = null;
let peerLookupDone = false;

/**
 * Resolve the counterparty of a trade branch through the trade detail.
 *
 * The conversation list carries only the peer name, so a deep link needs the
 * participant projection to learn the account id. A failure only hides the chat
 * entry point and never affects reading the archived history.
 */
async function resolveTradePeer(): Promise<void> {
  const id = tradeId.value;
  if (
    kind.value !== "trade" ||
    !id ||
    tradePeerId.value ||
    peerLookupDone ||
    peerRequestFor === id
  ) {
    return;
  }
  peerRequestFor = id;
  try {
    const trade = await getTrade(id);
    if (kind.value !== "trade" || tradeId.value !== id) return;
    const peer = trade.buyer.id === session.accountId.value ? trade.seller : trade.buyer;
    tradePeerId.value = peer.id;
    rememberPeer("trade", conversationId.value, peer.display_name, peer.id);
  } catch {
    // Reading history stays available even when the trade projection is unavailable.
  } finally {
    peerLookupDone = true;
    if (peerRequestFor === id) peerRequestFor = null;
  }
}

function loadTail(): Promise<void> {
  refreshPending = true;
  refreshInFlight ??= Promise.resolve().then(refreshTail);
  return refreshInFlight;
}

async function refreshTail(): Promise<void> {
  try {
    while (refreshPending && !abort.signal.aborted) {
      refreshPending = false;
      const firstLoad = !loaded.value;
      loading.value = firstLoad;
      error.value = null;
      let afterSeq = latestSeq.value;
      let more: boolean;
      do {
        const page = await listMessages(
          kind.value,
          conversationId.value,
          { limit: pageSize, after_seq: afterSeq },
          abort.signal,
        );
        if (abort.signal.aborted) return;
        const followTail = !loaded.value || isAtBottom();
        archived.value = page.branch_status === "archived";
        if (kind.value === "trade") {
          tradeId.value = page.trade_id;
          void resolveTradePeer();
        }
        if (!loaded.value) {
          oldestSeq.value = page.next_before_seq ?? null;
          hasOlder.value = page.items.length >= pageSize;
        }
        messages.value = [...messages.value, ...page.items];
        loaded.value = true;
        loading.value = false;
        afterSeq = page.next_after_seq ?? afterSeq;
        more = !firstLoad && page.items.length === pageSize && page.next_after_seq != null;
        await nextTick();
        if (followTail && !abort.signal.aborted) scrollToBottom();
      } while (more && !abort.signal.aborted);
      void markRead();
    }
  } catch (caught) {
    if (!abort.signal.aborted) {
      if (loaded.value) notify.error(problemMessage(caught));
      else error.value = caught;
    }
  } finally {
    loading.value = false;
    refreshInFlight = undefined;
  }
}

async function loadOlder(): Promise<void> {
  if (loadingOlder.value || oldestSeq.value === null) return;
  loadingOlder.value = true;
  const element = scroller.value;
  const previousHeight = element?.scrollHeight ?? 0;
  try {
    const page = await listMessages(
      kind.value,
      conversationId.value,
      { before_seq: oldestSeq.value, limit: pageSize },
      abort.signal,
    );
    if (abort.signal.aborted) return;
    messages.value = [...page.items, ...messages.value];
    oldestSeq.value = page.next_before_seq ?? null;
    hasOlder.value = page.items.length >= pageSize;
    await nextTick();
    // Keep the reading position when older messages are prepended.
    if (element) element.scrollTop = element.scrollHeight - previousHeight;
  } catch (caught) {
    if (!abort.signal.aborted) notify.error(problemMessage(caught));
  } finally {
    loadingOlder.value = false;
  }
}

function isAtBottom(): boolean {
  const element = scroller.value;
  return !!element && element.scrollHeight - element.scrollTop - element.clientHeight <= 24;
}

async function markRead(): Promise<void> {
  if (updatingRead || abort.signal.aborted) return;
  updatingRead = true;
  try {
    while (!abort.signal.aborted && isAtBottom()) {
      const displayedSeq = latestSeq.value ?? 0;
      if (displayedSeq <= acknowledgedSeq) break;
      const result = await advanceReadProgress(
        kind.value,
        conversationId.value,
        displayedSeq,
        newIdempotencyKey(),
      );
      if (result.last_read_seq < displayedSeq) break;
      acknowledgedSeq = result.last_read_seq;
    }
  } catch {
    // A subsequent visit or new message can retry the read update.
  } finally {
    updatingRead = false;
  }
}

async function send(): Promise<void> {
  const body = draft.value.trim();
  if (!body || sending.value || archived.value) return;
  sending.value = true;
  try {
    await sendMessage(kind.value, conversationId.value, { body }, newIdempotencyKey());
    if (abort.signal.aborted) return;
    if (draft.value.trim() === body) draft.value = "";
    await loadTail();
    if (abort.signal.aborted) return;
    resizeComposer();
    scrollToBottom();
    void markRead();
  } catch (caught) {
    if (!abort.signal.aborted) notify.error(problemMessage(caught));
  } finally {
    sending.value = false;
  }
}

function onComposerKeydown(event: KeyboardEvent): void {
  // Enter belongs to the IME candidate list while composing.
  if (!shouldSendOnEnter(event, composing)) return;
  event.preventDefault();
  void send();
}

function onCompositionStart(): void {
  composing = true;
}

function onCompositionEnd(): void {
  composing = false;
}

function resizeComposer(): void {
  const element = composer.value;
  if (!element) return;
  element.style.blockSize = "auto";
  element.style.blockSize = `${Math.min(element.scrollHeight, 160)}px`;
}

function scrollToBottom(): void {
  const element = scroller.value;
  if (element) element.scrollTop = element.scrollHeight;
}

function goBack(): void {
  void router.push({ name: "conversations" });
}

function onRealtimeFrame(frame: { event_type: string; data: Record<string, unknown> }): void {
  if (frame.event_type !== "message_created" && frame.event_type !== "conversation_archived") {
    return;
  }
  if (String(frame.data.conversation_kind) !== kind.value) return;
  if (String(frame.data.conversation_id) !== conversationId.value) return;
  if (
    frame.event_type === "message_created" &&
    typeof frame.data.message_seq === "number" &&
    frame.data.message_seq <= (latestSeq.value ?? 0)
  ) {
    return;
  }
  void loadTail();
}

watch(draft, () => {
  void nextTick(resizeComposer);
});

onMounted(() => {
  void loadTail();
  // After sync_reset the shell reloads every registered snapshot before resuming.
  unregisterReloader = registerSnapshotReloader(() => loadTail());
  unsubscribe = subscribeRealtime(onRealtimeFrame);
});

onBeforeUnmount(() => {
  abort.abort();
  unsubscribe?.();
  unregisterReloader?.();
});
</script>

<template>
  <section class="thread">
    <header class="thread__head">
      <button type="button" class="thread__back" aria-label="返回消息列表" @click="goBack">
        ←
      </button>
      <div class="thread__title">
        <h2>{{ heading }}</h2>
        <span class="muted">
          {{ archived ? "已归档 · 仅可查看" : title }}
          <template v-if="realtimeState === 'reconnecting'"> · 正在重新连接…</template>
          <template v-else-if="realtimeState === 'unauthenticated'"> · 登录状态已失效</template>
        </span>
      </div>
      <RouterLink
        v-if="kind === 'trade' && tradeId"
        :to="{ name: 'trade-detail', params: { tradeId } }"
        class="btn btn--ghost thread__trade-link"
      >
        查看交易
      </RouterLink>
      <StartChatButton
        v-if="kind === 'trade' && tradePeerId"
        :target-account-id="tradePeerId"
        :target-name="peerName(kind, conversationId) ?? ''"
        variant="ghost"
      />
    </header>

    <LoadingBlock v-if="loading" label="正在加载消息…" />
    <ErrorNotice v-else-if="error" :error="error" @retry="loadTail" />
    <template v-else>
      <div ref="scroller" class="thread__scroll" @scroll.passive="markRead">
        <div v-if="hasOlder" class="thread__older">
          <button type="button" class="btn btn--small" :disabled="loadingOlder" @click="loadOlder">
            {{ loadingOlder ? "加载中…" : "加载更早的消息" }}
          </button>
        </div>
        <p v-if="!messages.length" class="muted thread__empty">还没有消息，发送第一条吧。</p>
        <ol class="thread__rows">
          <template v-for="row in rows" :key="row.key">
            <li v-if="row.kind === 'date'" class="day">{{ row.label }}</li>
            <li v-else-if="row.system" class="event" :class="{ 'event--merged': row.merged }">
              <span class="event__text">{{ row.message.body }}</span>
            </li>
            <li
              v-else
              class="bubble-row"
              :class="{
                'bubble-row--mine': row.mine,
                'bubble-row--merged': row.merged,
              }"
            >
              <div class="bubble">
                <div v-if="!row.merged" class="bubble__meta">
                  <span class="bubble__sender">{{ row.message.sender.display_name }}</span>
                  <time
                    class="muted"
                    :datetime="row.message.created_at"
                    :title="formatDateTime(row.message.created_at)"
                  >
                    {{ formatRelative(row.message.created_at) }}
                  </time>
                </div>
                <p class="bubble__body pre-line break-anywhere">{{ row.message.body }}</p>
              </div>
            </li>
          </template>
        </ol>
      </div>

      <form v-if="!archived" class="composer" @submit.prevent="send">
        <label class="visually-hidden" for="message-input">消息内容</label>
        <textarea
          id="message-input"
          ref="composer"
          v-model="draft"
          class="textarea composer__input"
          rows="1"
          maxlength="2000"
          placeholder="输入消息，回车发送，Shift + 回车换行"
          @input="resizeComposer"
          @keydown="onComposerKeydown"
          @compositionstart="onCompositionStart"
          @compositionend="onCompositionEnd"
        />
        <button
          type="submit"
          class="btn btn--primary composer__send"
          :disabled="sending || !draft.trim()"
        >
          {{ sending ? "发送中…" : "发送" }}
        </button>
      </form>
      <p v-else class="banner banner--info composer composer--readonly">
        该会话已归档，不能再发送消息；历史消息仍可查看。
      </p>
    </template>
  </section>
</template>

<style scoped>
.thread {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  flex: 1;
  min-block-size: 0;
  min-inline-size: 0;
}

.thread__head {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding-block-end: var(--space-2);
  border-block-end: 1px solid var(--line);
}

.thread__back {
  flex: 0 0 auto;
  inline-size: 2rem;
  block-size: 2rem;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: var(--surface);
  cursor: pointer;
  font-size: 1rem;
  line-height: 1;
}

.thread__title {
  display: flex;
  flex-direction: column;
  min-inline-size: 0;
}

.thread__trade-link {
  flex: 0 0 auto;
  margin-inline-start: auto;
}

.thread__title h2 {
  margin: 0;
  font-size: 1rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.thread__title .muted {
  font-size: 0.75rem;
}

.thread__scroll {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  flex: 1;
  min-block-size: 0;
  overscroll-behavior: contain;
  overflow-y: auto;
  padding-inline-end: var(--space-1);
}

.thread__older {
  display: flex;
  justify-content: center;
  padding-block-end: var(--space-2);
}

.thread__empty {
  padding-block: var(--space-6);
  text-align: center;
}

.thread__rows {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin: 0;
  padding: 0;
  list-style: none;
}

.day {
  align-self: center;
  margin-block: var(--space-3) var(--space-1);
  padding: 0.125rem var(--space-3);
  font-size: 0.6875rem;
  color: var(--ink-faint);
  background: var(--surface-sunken);
  border-radius: 999px;
}

.event {
  align-self: center;
  max-inline-size: 90%;
  text-align: center;
}

.event--merged {
  margin-block-start: calc(-1 * var(--space-2));
}

.event__text {
  display: inline-block;
  padding: 0.125rem var(--space-2);
  font-size: 0.75rem;
  color: var(--ink-soft);
  background: var(--surface-sunken);
  border-radius: var(--radius-sm);
}

.bubble-row {
  display: flex;
  justify-content: flex-start;
}

.bubble-row--mine {
  justify-content: flex-end;
}

/* Short messages stay as wide as their content instead of filling the column. */
.bubble {
  inline-size: fit-content;
  max-inline-size: min(75%, 32rem);
  padding: var(--space-2) var(--space-3);
  background: #f4f8f5;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
}

.bubble-row--mine .bubble {
  background: var(--brand-soft);
  border-color: #cbe3d4;
}

.bubble-row--merged {
  margin-block-start: calc(-1 * var(--space-1));
}

.bubble__meta {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
  margin-block-end: 0.125rem;
}

.bubble__sender {
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--ink-soft);
}

.bubble__body {
  margin: 0;
  font-size: 0.875rem;
}

.composer {
  display: flex;
  flex: 0 0 auto;
  gap: var(--space-2);
  align-items: flex-end;
  border-block-start: 1px solid var(--line);
  padding-block-start: var(--space-3);
}

.composer__input {
  flex: 1;
  min-inline-size: 0;
  min-block-size: 2.5rem;
  max-block-size: 10rem;
  resize: none;
  overflow-y: auto;
}

.composer__send {
  flex: 0 0 auto;
  align-self: stretch;
  min-inline-size: 5rem;
}

.composer--readonly {
  display: block;
  margin: 0;
}
</style>
