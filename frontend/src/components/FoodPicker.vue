<script setup lang="ts">
import { computed, ref } from 'vue'
import type { Food } from '../lib/api'
const props=defineProps<{foods:Food[];modelValue:string}>()
const emit=defineEmits<{ 'update:modelValue':[value:string] }>()
const query=ref(''),category=ref('')
const categories=computed(()=>[...new Set(props.foods.map(f=>f.category||'原有食品'))].sort())
const clean=(value:string)=>value.toLowerCase().replace(/[\s（）()·、，,]/g,'')
const matches=computed(()=>{
 const key=clean(query.value)
 return props.foods.filter(food=>(!category.value||(food.category||'原有食品')===category.value)&&
  (!key||clean([food.name,...(food.aliases||[])].join(' ')).includes(key)))
})
const visible=computed(()=>{
 const result=matches.value.slice(0,60)
 const selected=props.foods.find(food=>food.code===props.modelValue)
 return selected&&!result.some(food=>food.code===selected.code)?[selected,...result]:result
})
function change(event:Event){emit('update:modelValue',(event.target as HTMLSelectElement).value)}
</script>
<template>
 <div class="food-picker">
  <label class="search-label">搜索食品库
   <input v-model="query" type="search" maxlength="60" placeholder="输入食物名或别名，如紫薯、鸡块"/>
  </label>
  <label>食品分类
   <select v-model="category"><option value="">全部分类</option><option v-for="name in categories" :key="name" :value="name">{{name}}</option></select>
  </label>
  <label>选择食品库条目
   <select :value="modelValue" @change="change">
    <option value="">请选择对应食物和生熟状态</option>
    <option v-for="food in visible" :key="food.code" :value="food.code">{{food.name}}{{food.preparation?' · '+food.preparation:''}} · {{food.kcal}} kcal/100g{{food.source_type==='ai_estimate'?' · AI估算':''}}</option>
   </select>
  </label>
  <span class="picker-hint" aria-live="polite">食品库共 {{foods.length}} 项；{{matches.length?'当前匹配 '+matches.length+' 项':'暂无匹配，请换关键词'}}{{matches.length>60?'，显示前 60 项，请缩小搜索范围':''}}。</span>
 </div>
</template>
<style scoped>
.food-picker{display:grid;gap:10px;min-width:0}
.food-picker label{display:grid;gap:6px;font-size:11px;color:#647e6a;min-width:0}
.food-picker input,.food-picker select{width:100%;max-width:100%;min-width:0;box-sizing:border-box;border:1px solid #dfe8df;border-radius:10px;padding:10px;color:#304e3a;background:#fafcf9;font-size:12px}
.picker-hint{font-size:10px;line-height:1.7;color:#8b9a8f}
</style>
