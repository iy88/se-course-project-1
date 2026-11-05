<template>
  <div class="text-input">
    <el-input v-bind="$attrs" :model-value="modelValue" :maxlength="undefined" :show-word-limit="false"
      @update:model-value="value => $emit('update:modelValue', value)"
      @compositionstart="composing = true" @compositionend="composing = false">
      <template v-for="(_, name) in $slots" #[name]="slotProps"><slot :name="name" v-bind="slotProps || {}" /></template>
    </el-input>
    <p class="text-limit" :class="{ 'text-limit--error': error }" role="status" aria-live="polite">
      {{ count }} / {{ limit }} · {{ error || (count === limit ? '已达字符上限' : `最多 ${limit} 个字符`) }}
    </p>
  </div>
</template>
<script setup>
import { computed, ref } from 'vue'
import { countText, textError } from '../api/text'
defineOptions({ inheritAttrs: false })
const props = defineProps({ modelValue: { type: String, default: '' }, limit: { type: Number, required: true } })
defineEmits(['update:modelValue'])
const composing = ref(false)
const count = computed(() => countText(props.modelValue))
const error = computed(() => composing.value ? '' : textError(props.modelValue, props.limit))
</script>
<style scoped>
.text-input { width: 100%; min-width: 0; }
.text-limit { margin: 3px 0; font-size: 12px; line-height: 1.5; color: var(--el-text-color-secondary); overflow-wrap: anywhere; }
.text-limit--error { color: var(--el-color-danger); }
</style>
