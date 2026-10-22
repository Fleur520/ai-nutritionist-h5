<script setup lang="ts">
import { computed, ref } from 'vue'
import { Search, SlidersHorizontal } from 'lucide-vue-next'
import type { Food } from '../lib/api'
const props = defineProps<{ foods: Food[]; modelValue: string; disabled?: boolean; initialQuery?: string; optional?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
const query = ref(props.initialQuery || ''), category = ref('')
const categories = computed(() => [...new Set(props.foods.map(food => food.category || '原有食品'))].sort())
const clean = (value: string) => value.toLowerCase().replace(/[\s（）()·、，,]/g, '')
const matches = computed(() => {
  const key = clean(query.value)
  return props.foods.filter(food => (!category.value || (food.category || '原有食品') === category.value) &&
    (!key || clean([food.name, ...(food.aliases || [])].join(' ')).includes(key)))
})
const visible = computed(() => {
  const result = matches.value.slice(0, 60)
  const selected = props.foods.find(food => food.code === props.modelValue)
  return selected && !result.some(food => food.code === selected.code) ? [selected, ...result] : result
})
function change(event: Event) { emit('update:modelValue', (event.target as HTMLSelectElement).value) }
</script>

<template>
  <div class="food-picker">
    <label class="search-label">搜索食品库
      <span class="picker-search"><Search :size="17" aria-hidden="true" /><input v-model="query" type="search" maxlength="60" placeholder="试试紫薯、鸡块、米饭" :disabled="disabled" /></span>
    </label>
    <details class="picker-filter">
      <summary><SlidersHorizontal :size="14" aria-hidden="true" />{{ category || '按分类缩小范围' }}</summary>
      <label>食品分类<select v-model="category" :disabled="disabled"><option value="">全部分类</option><option v-for="name in categories" :key="name" :value="name">{{ name }}</option></select></label>
    </details>
    <label>{{ optional ? '关联食品库（可选）' : '对应的食物' }}
      <select :value="modelValue" :disabled="disabled" @change="change">
        <option value="">{{ optional ? '不关联，使用照片 AI 估算' : '请选择食物与生熟状态' }}</option>
        <option v-for="food in visible" :key="food.code" :value="food.code">{{ food.name }}{{ food.preparation ? ' · ' + food.preparation : '' }} · {{ food.kcal }} kcal/100g{{ food.source_type === 'ai_estimate' ? ' · AI估算' : '' }}</option>
      </select>
    </label>
    <span class="picker-hint" aria-live="polite">共 {{ foods.length }} 项 · {{ matches.length ? '找到 ' + matches.length + ' 项食物' : '没有找到，试试别名或其他分类' }}{{ matches.length > 60 ? ' · 显示前 60 项，可继续搜索' : '' }}</span>
  </div>
</template>

<style scoped>
.food-picker{display:grid;gap:12px;min-width:0}.food-picker label{display:grid;gap:8px;font-size:13px;font-weight:500;color:#5e7565;min-width:0}.food-picker input,.food-picker select{width:100%;max-width:100%;min-width:0;box-sizing:border-box;border:1px solid #dfe8df;border-radius:12px;padding:11px 12px;color:#304e3a;background:#fafcf9;font-size:16px;min-height:48px}.food-picker select{padding-right:28px;text-overflow:ellipsis}.picker-search{display:flex;align-items:center;gap:8px;background:#fafcf9;border:1px solid #dfe8df;border-radius:12px;padding:0 12px}.picker-search svg{color:#91a294;flex-shrink:0}.picker-search input{background:transparent;border:0;padding:11px 0;border-radius:0}.picker-search:focus-within{outline:2px solid #8ab18c;outline-offset:2px}.picker-search input:focus-visible{outline:none}.picker-search input::placeholder{font-size:14px;color:#8c9b90}.picker-filter{font-size:12px;color:#718674}.picker-filter summary{display:flex;align-items:center;gap:6px;cursor:pointer;min-height:32px;list-style:none;max-width:100%;overflow-wrap:anywhere}.picker-filter summary::-webkit-details-marker{display:none}.picker-filter summary::after{content:'⌄';margin-left:auto;font-size:16px;color:#9cae9f}.picker-filter[open] summary::after{transform:rotate(180deg)}.picker-filter>label{margin-top:8px}.picker-hint{font-size:11px;line-height:1.7;color:#8b9a8f;margin-top:-4px}
</style>
