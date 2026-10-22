<script setup lang="ts">
import { ref, watch, onMounted, onBeforeUnmount } from 'vue'
import { CalendarDays, Flame, RefreshCw, Utensils, ArrowRight, LoaderCircle } from 'lucide-vue-next'
import { api, type Meal, type Summary } from '../lib/api'

const emit = defineEmits<{ go: [value: string] }>()
function chinaDay() {
  const parts = new Intl.DateTimeFormat('en-US', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date())
  const value = (type: string) => parts.find(part => part.type === type)?.value || ''
  return `${value('year')}-${value('month')}-${value('day')}`
}
const today = chinaDay()
const day = ref(today), meals = ref<Meal[]>([]), summary = ref<Summary | null>(null), loading = ref(true), error = ref('')
const label: Record<string, string> = { breakfast: '早餐', lunch: '午餐', dinner: '晚餐', snack: '加餐' }
let requestId = 0
async function reload() {
  const currentRequest = ++requestId
  loading.value = true
  error.value = ''
  try {
    const [records, totals] = await Promise.all([
      api<Meal[]>('/meals?day=' + day.value),
      api<Summary>('/nutrition/summary?days=7'),
    ])
    if (currentRequest !== requestId) return
    meals.value = records
    summary.value = totals
  } catch (failure) {
    if (currentRequest === requestId) error.value = failure instanceof Error ? failure.message : '暂时无法加载记录，请稍后重试'
  } finally {
    if (currentRequest === requestId) loading.value = false
  }
}
watch(day, reload)
onMounted(reload)
onBeforeUnmount(() => { requestId++ })
const total = (meal: Meal) => meal.items.reduce((sum, item) => sum + item.kcal, 0)
const mealTime = (value: string) => new Date(value).toLocaleTimeString('zh-CN', { timeZone: 'Asia/Shanghai', hour: '2-digit', minute: '2-digit', hour12: false })
const nutrition = (value: number | undefined) => Number((value || 0).toFixed(1))
</script>

<template>
  <section class="page history-page">
    <header class="page-header">
      <div class="eyebrow">YOUR FOOD JOURNAL</div>
      <h1 class="page-title">每一餐，都值得记录。</h1>
      <p class="page-subtitle">慢慢了解自己的饮食习惯，发现每天的小变化。</p>
    </header>
    <div class="report-card" :aria-busy="loading">
      <div class="report-top"><span>最近 7 天 · 已记录能量</span><Flame :size="20" aria-hidden="true" /></div>
      <strong>{{ loading || error ? '—' : Math.round(summary?.totals.kcal || 0) }}<small> kcal</small></strong>
      <div class="report-breakdown">
        <span>蛋白质 <b>{{ loading || error ? '—' : nutrition(summary?.totals.protein) }}</b> g</span>
        <span>碳水 <b>{{ loading || error ? '—' : nutrition(summary?.totals.carbs) }}</b> g</span>
        <span>脂肪 <b>{{ loading || error ? '—' : nutrition(summary?.totals.fat) }}</b> g</span>
      </div>
    </div>
    <div class="section-header history-section-header">
      <div><h2>饮食日记</h2><p class="section-copy">{{ day === today ? '看看今天吃了什么' : '回顾这一天的好好吃饭' }}</p></div>
      <label class="date-control"><CalendarDays :size="17" aria-hidden="true" /><input type="date" v-model="day" :max="today" aria-label="选择记录日期" /></label>
    </div>
    <div v-if="loading" class="empty-state journal-state" role="status"><LoaderCircle :size="28" class="spinning" /><strong>正在翻开你的饮食日记…</strong></div>
    <div v-else-if="error" class="empty-state journal-state journal-error" role="alert">
      <strong>记录暂时没有加载出来</strong><p>{{ error }}</p>
      <button type="button" class="secondary-action" @click="reload"><RefreshCw :size="16" />重新加载</button>
    </div>
    <div v-else-if="!meals.length" class="empty-state journal-state">
      <div class="journal-empty-icon"><Utensils :size="25" /></div><strong>从记录一餐开始</strong><p>这一天还没有饮食记录。<br />拍张照片，把认真吃饭的小事留下来。</p>
      <button type="button" class="secondary-action" @click="emit('go', 'scan')">去记录一餐<ArrowRight :size="16" /></button>
    </div>
    <template v-else>
      <article v-for="meal in meals" :key="meal.id" class="meal-card">
        <div class="meal-head"><div><span class="meal-dot"></span><strong>{{ label[meal.meal_type] || meal.meal_type }}</strong><small>{{ mealTime(meal.eaten_at) }}</small></div><strong>{{ Math.round(total(meal)) }} <small>kcal</small></strong></div>
        <div v-for="item in meal.items" :key="item.id" class="meal-line"><span>{{ item.name }}<small>{{ item.grams }} 克<span v-if="item.source_type === 'ai_estimate'"> · 照片 AI 估算 · 未核验</span></small></span><span>{{ nutrition(item.kcal) }} kcal</span></div>
        <img v-if="meal.image_id" :src="'/api/images/' + meal.image_id" class="meal-photo" alt="本餐照片" loading="lazy" />
      </article>
    </template>
  </section>
</template>

<style scoped>
.section-copy{margin:5px 0 0;font-size:12px;line-height:1.5;color:#7b8d81}.history-section-header{align-items:center;flex-wrap:wrap}.date-control{min-height:44px;background:white}.date-control input{min-height:32px;max-width:138px;width:138px;font-size:14px;padding:0}.journal-state{display:flex;flex-direction:column;align-items:center;gap:12px;padding:30px 20px;background:white;border:1px solid #e5ebe5}.journal-state strong{color:#355b44;font-size:16px}.journal-state p{font-size:14px;line-height:1.8;margin:0;color:#7a8a7f;overflow-wrap:anywhere}.journal-empty-icon{width:56px;height:56px;border-radius:18px;display:grid;place-items:center;background:#edf3e9;color:#5b805d}.journal-error{background:#fff9f5}.secondary-action{display:inline-flex;align-items:center;justify-content:center;gap:8px;min-height:44px;border-radius:12px;padding:10px 17px;background:#edf4ec;color:#245b43;font-size:14px;font-weight:600}.meal-line{align-items:flex-start;gap:12px}.meal-line>span:first-child{min-width:0;overflow-wrap:anywhere}.meal-line>span:last-child{white-space:nowrap}.meal-line small{display:block;font-size:12px;color:#8b998f;margin-top:3px}.meal-head{gap:8px}.meal-head>div{flex-wrap:wrap}.meal-head>strong{white-space:nowrap}.report-breakdown b{font-weight:600}
</style>
