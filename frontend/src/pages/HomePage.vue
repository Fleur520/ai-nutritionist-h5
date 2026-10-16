<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ArrowUpRight, ArrowRight, Camera, MessageCircle, Leaf, Beef, Wheat, Droplets, NotebookPen, RefreshCw } from 'lucide-vue-next'
import { api, type Summary } from '../lib/api'
import { reportsEnabled } from '../lib/features'

const emit=defineEmits<{go:[value:string]}>()
const summary=ref<Summary|null>(null),loading=ref(true),error=ref('')
const today=new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'long',day:'numeric',weekday:'long'}).format(new Date())
const hasRecords=computed(()=>!!summary.value?.totals.kcal)
const stats=[{key:'protein',name:'蛋白质',unit:'g',icon:Beef},{key:'carbs',name:'碳水',unit:'g',icon:Wheat},{key:'fat',name:'脂肪',unit:'g',icon:Droplets}]
function value(key:string){return Math.round(Number((summary.value?.totals as unknown as Record<string,number>|undefined)?.[key]||0))}
async function reload(){
  loading.value=true;error.value=''
  try{summary.value=await api<Summary>('/nutrition/summary?days=1')}
  catch(e){error.value=e instanceof Error?e.message:'今日记录暂时没有加载成功'}
  finally{loading.value=false}
}
onMounted(reload)
</script>

<template>
  <section class="page page-home">
    <div class="home-heading"><span class="eyebrow">每一天，都值得好好吃饭</span><span class="home-date">{{today}}</span></div>
    <h1 class="page-title home-title">从一餐开始，<br/>照顾好自己<span class="title-leaf">✳</span></h1>
    <p class="page-subtitle">记录饮食的小习惯，慢慢找到自己的健康节奏。</p>

    <div class="hero-card" :aria-busy="loading">
      <div class="hero-top"><span><span class="status-dot"></span> 今日营养概览</span><button @click="emit('go','history')">看记录 <ArrowUpRight :size="14"/></button></div>
      <div v-if="error" class="hero-error" role="alert"><p>今日记录暂时无法加载</p><button @click="reload"><RefreshCw :size="15"/>重新加载</button></div>
      <template v-else>
        <div class="calorie-main">
          <div><div class="big-value">{{loading?'—':value('kcal')}}<small>kcal</small></div><p>{{loading?'正在整理你的记录…':'今日已记录能量'}}</p></div>
          <div class="hero-visual" aria-hidden="true"><div class="plate-ring"><Leaf :size="35" :stroke-width="1.5"/><i></i><b></b></div></div>
        </div>
        <div class="metric-row"><div v-for="stat in stats" :key="stat.key" class="metric"><component :is="stat.icon" :size="15"/><b>{{loading?'—':value(stat.key)}}<small>{{stat.unit}}</small></b><span>{{stat.name}}</span></div></div>
      </template>
    </div>

    <div class="section-header"><div><h2>给健康，一点行动</h2><p class="section-copy">不必完美，从眼前这一餐开始。</p></div></div>
    <div class="quick-grid">
      <button class="quick-card scan" @click="emit('go','scan')"><div class="quick-card-top"><span class="quick-icon"><Camera :size="24"/></span><ArrowUpRight :size="18"/></div><h3>拍照记一餐</h3><p>看见食物，了解营养</p><span class="quick-link">现在记录 <ArrowRight :size="14"/></span></button>
      <button class="quick-card ask" @click="emit('go','chat')"><div class="quick-card-top"><span class="quick-icon"><MessageCircle :size="24"/></span><ArrowUpRight :size="18"/></div><h3>聊聊怎么吃</h3><p>把饮食困惑，交给 AI</p><span class="quick-link">问问营养师 <ArrowRight :size="14"/></span></button>
    </div>

    <button class="tip-card journal-link" @click="emit('go','history')"><span class="tip-icon"><NotebookPen :size="22"/></span><span><b>你的饮食日记</b><small>{{hasRecords?'看看今天的记录与最近 7 天的变化':'让每一餐，都留下好好生活的痕迹'}}</small></span><ArrowRight :size="18"/></button>
    <button v-if="reportsEnabled" class="tip-card" @click="emit('go','report')"><span class="tip-icon"><Leaf :size="21"/></span><span><b>我的营养报告</b><small>用 7 日或 30 日记录，了解饮食变化</small></span><ArrowRight :size="18"/></button>
    <div class="daily-note"><Leaf :size="17"/><p>吃得丰富一点，生活从容一点。<span>照片识别和营养数据为估算，请按实际分量确认。</span></p></div>
  </section>
</template>
