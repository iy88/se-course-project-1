<script setup lang="ts">
/*
 * Master–detail shell for the message screen.
 *
 * Wide screens show the branch list and the thread side by side; narrow screens
 * show one at a time, so the thread carries its own compact header. The list pane
 * survives branch switches because it lives in the parent route component.
 */
import { computed } from "vue";
import { useRoute } from "vue-router";
import ConversationListPane from "./ConversationListPane.vue";

const route = useRoute();
const hasThread = computed(() => Boolean(route.params.conversationId));
</script>

<template>
  <div class="conversations" :class="{ 'conversations--thread': hasThread }">
    <header class="conversations__head">
      <div class="stack stack--tight">
        <h1>消息</h1>
        <p class="muted">私聊与每笔交易各自保留独立会话，已读进度按会话分别记录。</p>
      </div>
    </header>

    <div class="conversations__body">
      <div class="conversations__list">
        <ConversationListPane />
      </div>
      <div class="conversations__detail">
        <RouterView :key="route.path" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.conversations {
  display: flex;
  flex-direction: column;
  flex: 1;
  gap: var(--space-4);
  min-block-size: 0;
  min-inline-size: 0;
}

.conversations__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3);
  flex-wrap: wrap;
}

.conversations__head h1 {
  margin: 0;
  font-size: 1.25rem;
}

.conversations__body {
  display: grid;
  gap: var(--space-4);
  flex: 1;
  grid-template: minmax(0, 1fr) / minmax(0, 1fr);
  min-block-size: 0;
}

.conversations__detail {
  display: none;
  min-block-size: 0;
  min-inline-size: 0;
}

.conversations--thread .conversations__detail {
  display: flex;
}

.conversations__list {
  overflow-y: auto;
}

@media (width < 60rem) {
  .conversations--thread .conversations__head,
  .conversations--thread .conversations__list {
    display: none;
  }
}

@media (width >= 60rem) {
  .conversations__body {
    grid-template-columns: minmax(16rem, 22rem) minmax(0, 1fr);
  }

  .conversations__detail {
    display: block;
    overflow-y: auto;
  }
}
</style>
