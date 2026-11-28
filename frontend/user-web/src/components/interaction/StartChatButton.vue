<script setup lang="ts">
/*
 * Start (or reopen) the one private chat with a known counterparty.
 *
 * The backend owns idempotency of the conversation, but the client keeps one key
 * across retries so a transport failure cannot create a second branch. No message
 * is sent and no purchase request is created here.
 */
import { computed, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { ensurePrivateConversation } from "../../api/conversations";
import { rememberPeer } from "../../app/conversation-directory";
import { IdempotencyKeys } from "../../app/keys";
import { problemMessage } from "../../app/problems";
import { session } from "../../app/session";
import { useToastStore } from "../../app/toast";

const { notify } = useToastStore();

const props = withDefaults(
  defineProps<{
    targetAccountId: string;
    targetName?: string;
    label?: string;
    variant?: "primary" | "ghost" | "default";
    small?: boolean;
  }>(),
  { targetName: "", label: "发私聊", variant: "default", small: false },
);

const router = useRouter();
const keys = new IdempotencyKeys();
const pending = ref(false);
const isSelf = computed(
  () => !props.targetAccountId || props.targetAccountId === session.accountId.value,
);
const accessibleLabel = computed(() =>
  props.targetName ? `${props.label}：${props.targetName}` : props.label,
);
const classes = computed(() => {
  const list = ["btn"];
  if (props.variant === "primary") list.push("btn--primary");
  if (props.variant === "ghost") list.push("btn--ghost");
  if (props.small) list.push("btn--small");
  return list;
});

watch(
  () => props.targetAccountId,
  () => {
    keys.reset();
  },
);

async function start(): Promise<void> {
  if (pending.value || isSelf.value) return;
  pending.value = true;
  try {
    const conversation = await ensurePrivateConversation(
      props.targetAccountId,
      keys.current("private-conversation"),
    );
    keys.rotate("private-conversation");
    rememberPeer(
      "chat",
      conversation.conversation_id,
      conversation.peer?.display_name || props.targetName,
      conversation.peer?.account_id || props.targetAccountId,
    );
    await router.push({
      name: "conversation",
      params: { kind: "chat", conversationId: conversation.conversation_id },
    });
  } catch (caught) {
    notify.error(problemMessage(caught));
  } finally {
    pending.value = false;
  }
}
</script>

<template>
  <span v-if="!isSelf" class="start-chat">
    <button
      type="button"
      :class="classes"
      :disabled="pending"
      :aria-busy="pending"
      :aria-label="accessibleLabel"
      @click="start"
    >
      {{ pending ? "正在打开…" : label }}
    </button>
  </span>
</template>

<style scoped>
.start-chat {
  display: inline-flex;
  flex-direction: column;
  gap: var(--space-1);
  align-items: flex-start;
}
</style>
