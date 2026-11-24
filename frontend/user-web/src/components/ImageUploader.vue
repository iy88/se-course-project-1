<script setup lang="ts">
/*
 * Multi-file image picker for one upload purpose.
 *
 * Authorises the upload, posts the bytes straight to the private bucket and only
 * keeps file ids that the backend has verified, so every id handed to the parent
 * is safe to reference from a product or profile write.
 */
import { computed, onBeforeUnmount, ref } from "vue";
import { newIdempotencyKey } from "../app/keys";
import { problemMessage } from "../app/problems";
import { uploadVerifiedFile } from "../api/files";
import type { FilePurpose, ResourceRef } from "../api/contracts";

const props = withDefaults(
  defineProps<{
    modelValue: string[];
    purpose: FilePurpose;
    target?: ResourceRef | null;
    label?: string;
    hint?: string;
    maxCount?: number;
    maxBytes?: number;
    disabled?: boolean;
  }>(),
  {
    target: null,
    label: "图片",
    hint: "支持 JPG、PNG",
    maxCount: 6,
    maxBytes: 104_857_600,
    disabled: false,
  },
);

const emit = defineEmits<{ "update:modelValue": [value: string[]] }>();

const previews = ref<Record<string, string>>({});
const uploading = ref(false);
const error = ref<string | null>(null);
const input = ref<HTMLInputElement | null>(null);

const fileIds = computed(() => props.modelValue);
const canAdd = computed(
  () => !props.disabled && !uploading.value && fileIds.value.length < props.maxCount,
);

function sync(next: string[]): void {
  emit("update:modelValue", next);
}

async function onFilesSelected(event: Event): Promise<void> {
  const picker = event.target as HTMLInputElement;
  const files = Array.from(picker.files ?? []);
  picker.value = "";
  if (!files.length) return;
  error.value = null;
  uploading.value = true;
  try {
    const accepted: string[] = [];
    for (const file of files) {
      if (file.size > props.maxBytes) {
        error.value = `${file.name} 超过 ${(props.maxBytes / 1024 / 1024).toFixed(0)} MB 上限。`;
        continue;
      }
      const fileId = await uploadVerifiedFile(props.purpose, file, props.target, () =>
        newIdempotencyKey(),
      );
      previews.value = { ...previews.value, [fileId]: URL.createObjectURL(file) };
      accepted.push(fileId);
    }
    if (accepted.length) sync([...fileIds.value, ...accepted].slice(0, props.maxCount));
  } catch (caught) {
    error.value = problemMessage(caught);
  } finally {
    uploading.value = false;
  }
}

function remove(fileId: string): void {
  const url = previews.value[fileId];
  if (url) URL.revokeObjectURL(url);
  const next = { ...previews.value };
  delete next[fileId];
  previews.value = next;
  sync(fileIds.value.filter((id) => id !== fileId));
}

// Local previews are object URLs; release them when the component goes away.
onBeforeUnmount(() => {
  for (const url of Object.values(previews.value)) URL.revokeObjectURL(url);
});
</script>

<template>
  <div class="uploader">
    <div class="uploader__head">
      <span class="field__label">{{ label }}</span>
      <span class="field__hint">{{ hint }} · 最多 {{ maxCount }} 张</span>
    </div>
    <ul class="uploader__grid">
      <li v-for="fileId in fileIds" :key="fileId" class="uploader__item">
        <img
          v-if="previews[fileId]"
          :src="previews[fileId]"
          :alt="`已选择的${label}`"
          class="uploader__image"
        />
        <span v-else class="uploader__placeholder mono">{{ fileId }}</span>
        <button
          type="button"
          class="uploader__remove"
          :aria-label="`移除${label}`"
          :disabled="disabled"
          @click="remove(fileId)"
        >
          ×
        </button>
      </li>
      <li v-if="canAdd" class="uploader__item uploader__item--add">
        <button type="button" class="uploader__add" @click="input?.click()">
          {{ uploading ? "上传中…" : "添加图片" }}
        </button>
      </li>
    </ul>
    <input
      ref="input"
      type="file"
      accept="image/jpeg,image/png"
      multiple
      class="visually-hidden"
      @change="onFilesSelected"
    />
    <p v-if="error" class="field__error">{{ error }}</p>
  </div>
</template>

<style scoped>
.uploader {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.uploader__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.uploader__grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(5rem, 1fr));
  gap: var(--space-2);
}

.uploader__item {
  position: relative;
  aspect-ratio: 1;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  overflow: hidden;
  background: #fbfcfb;
}

.uploader__image {
  inline-size: 100%;
  block-size: 100%;
  object-fit: cover;
}

.uploader__placeholder {
  display: grid;
  place-items: center;
  inline-size: 100%;
  block-size: 100%;
  font-size: 0.6875rem;
  color: var(--ink-faint);
}

.uploader__remove {
  position: absolute;
  inset-block-start: 0.125rem;
  inset-inline-end: 0.125rem;
  inline-size: 1.375rem;
  block-size: 1.375rem;
  border: 0;
  border-radius: 50%;
  background: rgb(24 36 32 / 62%);
  color: #fff;
  cursor: pointer;
  line-height: 1;
}

.uploader__item--add {
  border-style: dashed;
}

.uploader__add {
  inline-size: 100%;
  block-size: 100%;
  border: 0;
  background: none;
  color: var(--brand);
  font-size: 0.75rem;
  cursor: pointer;
}
</style>
