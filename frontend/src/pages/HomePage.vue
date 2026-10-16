<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ArrowUpRight, Camera, MessageCircle, ChevronRight, Flame, Beef, Wheat, Droplets } from 'lucide-vue-next'
import { api, type Summary } from '../lib/api'
import { reportsEnabled } from '../lib/features'
const emit=defineEmits<{go:[value:string]}>()
const summary=ref<Summary|null>(null)
onMounted(async()=>{try{summary.value=await api('/nutrition/summary?days=1')}catch{}})
function statValue(key:string){return Math.round(Number((summary.value?.totals as unknown as Record<string,number>|undefined)?.[key]||0))}
const stats=[{key:'protein',name:'蛋白质',unit:'g',icon:Beef},{key:'carbs',name:'碳水',unit:'g',icon:Wheat},{key:'fat',name:'脂肪',unit:'g',icon:Droplets}]
</script>
<template><section class="page page-home">
  <div class="eyebrow">YOUR DAILY WELLNESS</div>
  <h1 class="page-title">今天，也好好吃饭 <span>✳</span></h1><p class="page-subtitle">记录你的日常，发现更适合自己的饮食节奏。</p>
  <div class="hero-card"><div class="hero-top"><span>今日营养概览</span><span class="hero-date">{{new Date().toLocaleDateString('zh-CN',{month:'long',day:'numeric'})}}</span></div>
    <div class="calorie-main"><div><div class="big-value">{{Math.round(summary?.totals.kcal||0)}}<small> kcal</small></div><p>今日已记录能量</p></div><div class="hero-visual"><span>🥑</span></div></div>
    <div class="metric-row"><div v-for="stat in stats" :key="stat.key" class="metric"><component :is="stat.icon" :size="15"/><b>{{statValue(stat.key)}}<small>{{stat.unit}}</small></b><span>{{stat.name}}</span></div></div>
  </div>
  <div class="section-header"><h2>你想做什么？</h2><span>开始健康的一天</span></div>
  <div class="quick-grid"><button class="quick-card scan" @click="emit('go','scan')"><div class="quick-icon"><Camera :size="23"/></div><h3>拍一张，识别热量</h3><p>AI 看懂你的每一餐</p><ArrowUpRight :size="20" class="quick-arrow"/></button><button class="quick-card ask" @click="emit('go','chat')"><div class="quick-icon"><MessageCircle :size="23"/></div><h3>问问 AI 营养师</h3><p>有依据的饮食建议</p><ArrowUpRight :size="20" class="quick-arrow"/></button></div>
  <button v-if="reportsEnabled" class="tip-card" @click="emit('go','report')"><span class="tip-icon">📋</span><span><b>生成 7 日 / 30 日健康报告</b><small>BiSheng Workflow · 饮食数据分析与建议</small></span><ChevronRight :size="19"/></button>
  <button class="tip-card" @click="emit('go','history')"><span class="tip-icon">✦</span><span><b>你的饮食日记</b><small>每天一点点，更了解自己的身体</small></span><ChevronRight :size="19"/></button>
  <div class="disclaimer">小提示：食物热量是估算值，照片无法准确判断食材重量、用油和隐藏配料。</div>
</section></template>
