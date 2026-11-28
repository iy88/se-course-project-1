<script setup lang="ts">
/*
 * Favourite control (API-PRD-029—031).
 *
 * The server decides whether the current product may be favourited. When the
 * status read answers 404 (hidden product, not favourited) the control stays
 * hidden instead of offering an action the backend would reject.
 */
import { onMounted, ref, watch } from "vue";
import { ApiError } from "../../api/errors";
import { addFavorite, getFavoriteStatus, removeFavorite } from "../../api/products";
import { IdempotencyKeys } from "../../app/keys";
import { problemMessage } from "../../app/problems";
import { useToastStore } from "../../app/toast";

const { notify } = useToastStore();

const props = defineProps<{ productId: string }>();

const favorited = ref(false);
const visible = ref(false);
const pending = ref(false);
const keys = new IdempotencyKeys();

async function load(): Promise<void> {
  try {
    const status = await getFavoriteStatus(props.productId);
    favorited.value = status.favorited;
    visible.value = status.valid || status.favorited;
  } catch (caught) {
    if (caught instanceof ApiError && caught.status === 404) {
      favorited.value = false;
      visible.value = false;
      return;
    }
    // Keep the button hidden until the status can be read rather than showing a
    // state the server has not confirmed.
    visible.value = false;
  }
}

onMounted(load);
watch(
  () => props.productId,
  () => {
    favorited.value = false;
    visible.value = false;
    void load();
  },
);

async function toggle(): Promise<void> {
  if (pending.value) return;
  pending.value = true;
  try {
    if (favorited.value) {
      const operation = "favorite-remove";
      await removeFavorite(props.productId, keys.current(operation));
      keys.rotate(operation);
      favorited.value = false;
      notify.info("已取消收藏。");
    } else {
      const operation = "favorite-add";
      const status = await addFavorite(props.productId, keys.current(operation));
      keys.rotate(operation);
      favorited.value = status.favorited;
      notify.success("已收藏。");
    }
  } catch (caught) {
    notify.error(problemMessage(caught));
  } finally {
    pending.value = false;
  }
}
</script>

<template>
  <button
    v-if="visible"
    type="button"
    class="btn"
    :class="{ 'btn--ghost': !favorited }"
    :aria-pressed="favorited"
    :disabled="pending"
    @click="toggle"
  >
    {{ favorited ? "已收藏" : "收藏" }}
  </button>
</template>
