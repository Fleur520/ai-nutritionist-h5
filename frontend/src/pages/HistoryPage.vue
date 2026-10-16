<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'
import { CalendarDays, Flame, ChevronDown } from 'lucide-vue-next'
import { api, type Meal, type Summary } from '../lib/api'
const day=ref(new Date().toISOString().slice(0,10)),meals=ref<Meal[]>([]),summary=ref<Summary|null>(null),loading=ref(false)
const label:{[key:string]:string}={breakfast:'早餐',lunch:'午餐',dinner:'晚餐',snack:'加餐'}
async function reload(){loading.value=true;try{meals.value=await api('/meals?day='+day.value);summary.value=await api('/nutrition/summary?days=7')}catch{}finally{loading.value=false}}
watch(day,reload);onMounted(reload)
const total=(m:Meal)=>m.items.reduce((s,x)=>s+x.kcal,0)
</script>
<template><section class="page history-page"><div class="eyebrow">YOUR FOOD JOURNAL</div><h1 class="page-title">每一餐，都是新记录。</h1><p class="page-subtitle">了解自己的营养摄入，让每天的变化看得见。</p>
<div class="report-card"><div class="report-top"><span>最近 7 天 · 已记录营养</span><Flame :size="18"/></div><strong>{{Math.round(summary?.totals.kcal||0)}}<small> kcal</small></strong><div class="report-breakdown"><span>蛋白质 {{summary?.totals.protein||0}}g</span><span>碳水 {{summary?.totals.carbs||0}}g</span><span>脂肪 {{summary?.totals.fat||0}}g</span></div></div>
<div class="section-header"><h2>饮食明细</h2><label class="date-control"><CalendarDays :size="17"/><input type="date" v-model="day"/></label></div>
<div v-if="loading" class="empty-state">正在加载记录…</div><div v-else-if="!meals.length" class="empty-state">这一天还没有记录，从拍下一餐开始吧。</div>
<div v-for="m in meals" :key="m.id" class="meal-card"><div class="meal-head"><div><span class="meal-dot"></span><strong>{{label[m.meal_type]||m.meal_type}}</strong><small>{{new Date(m.eaten_at).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'})}}</small></div><strong>{{Math.round(total(m))}} <small>kcal</small></strong></div><div v-for="item in m.items" :key="item.id" class="meal-line"><span>{{item.name}} · {{item.grams}}g</span><span>{{item.kcal}} kcal</span></div><img v-if="m.image_id" :src="'/api/images/'+m.image_id" class="meal-photo" alt="本餐照片"/></div>
</section></template>
