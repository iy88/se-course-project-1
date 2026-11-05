<template>
  <div class="text-field">
    <van-field ref="field" v-bind="$attrs" :model-value="modelValue" :maxlength="undefined" :show-word-limit="false"
      :rules="rules" @update:model-value="value => $emit('update:modelValue', value)"
      @compositionstart="composing = true" @compositionend="composing = false">
      <template v-for="(_, name) in $slots" #[name]="slotProps"><slot :name="name" v-bind="slotProps || {}" /></template>
    </van-field>
    <p class="text-limit" :class="{ 'text-limit--error': error }" role="status" aria-live="polite">
      {{ count }} / {{ limit }} · {{ error || (count === limit ? '已达字符上限' : `最多 ${limit} 个字符`) }}
    </p>
  </div>
</template>
<script setup>
import { computed, ref, useAttrs } from 'vue'
import { countText, textError } from '../api/text'
defineOptions({ inheritAttrs: false })
const props = defineProps({ modelValue: { type: String, default: '' }, limit: { type: Number, required: true } })
defineEmits(['update:modelValue'])
const attrs = useAttrs()
const field = ref(null)
const composing = ref(false)
const count = computed(() => countText(props.modelValue))
const error = computed(() => composing.value ? '' : textError(props.modelValue, props.limit))
const rules = computed(() => [...(attrs.rules || []), { validator: value => !textError(value, props.limit), message: `最多 ${props.limit} 个字符` }])
defineExpose({ focus: () => field.value?.focus() })
</script>
<style scoped>
.text-field { min-width: 0; flex: 1; }
.text-limit { margin: 0; padding: 2px 16px 8px; color: var(--ink-meta); font-size: 12px; overflow-wrap: anywhere; }
.text-limit--error { color: var(--danger, #b3261e); }
</style>
