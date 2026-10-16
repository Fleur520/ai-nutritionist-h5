<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ArrowLeft, FileText, Leaf, LoaderCircle, RefreshCw } from 'lucide-vue-next'
import { api, type NutritionReport, type ReportMeta } from '../lib/api'

const emit = defineEmits<{go:[value:string]}>()
const days = ref<7|30>(7)
const report = ref<NutritionReport|null>(null)
const list = ref<ReportMeta[]>([])
const loading = ref(false)
const error = ref('')
async function refresh(){ list.value = await api<ReportMeta[]>('/reports').catch(()=>[]) }
onMounted(refresh)
async function open(id:string){
  error.value='';loading.value=true
  try{report.value=await api<NutritionReport>('/reports/'+encodeURIComponent(id))}
  catch(e){error.value=e instanceof Error?e.message:'无法读取报告'}
  finally{loading.value=false}
}
async function generate(){
  error.value='';loading.value=true
  try{
    report.value=await api<NutritionReport>('/reports/generate?days='+days.value,{method:'POST'})
    await refresh()
  }catch(e){error.value=e instanceof Error?e.message:'生成失败，请检查 BiSheng 工作流配置'}
  finally{loading.value=false}
}
function formatDate(value:string){return value?.replace('T',' ').slice(0,16)||''}
</script>
<template>
  <section class="page report-page">
    <button class="report-back" @click="emit('go','home')"><ArrowLeft :size="17"/> 返回首页</button>
    <div class="eyebrow">WELLNESS REPORT</div>
    <h1 class="page-title">营养健康报告 <Leaf :size="23" class="report-leaf"/></h1>
    <p class="page-subtitle">以你真实保存的饮食记录为依据，交由 BiSheng 工作流分析并给出生活方式建议。</p>
    <div class="report-panel">
      <div class="section-header"><h2>选择分析周期</h2></div>
      <div class="report-options">
        <button :class="{active:days===7}" @click="days=7">近 7 天</button>
        <button :class="{active:days===30}" @click="days=30">近 30 天</button>
      </div>
      <button class="primary-button" :disabled="loading" @click="generate">
        <LoaderCircle v-if="loading" :size="18" class="spinning"/><FileText v-else :size="18"/>
        {{loading?'工作流分析中，请稍候…':'生成健康报告'}}
      </button>
    </div>
    <p v-if="error" class="error">{{error}}</p>
    <div v-if="report" class="report-output">
      <div class="report-title-row"><h2>{{report.days}} 日饮食健康报告</h2><span>{{report.source==='demo'?'演示报告':'BiSheng 1.3.1'}}</span></div>
      <div class="report-stats">
        <div><small>有记录天数</small><strong>{{report.summary.recorded_days}} / {{report.days}}</strong></div>
        <div><small>期间记录能量</small><strong>{{Math.round(report.summary.totals.kcal)}} <em>kcal</em></strong></div>
      </div>
      <div class="report-text">{{report.content}}</div>
      <p class="microcopy">营养建议仅用于一般健康管理，不作为疾病诊断或医疗处方。</p>
    </div>
    <div class="section-header"><h2>历史报告</h2><button class="text-action" @click="refresh"><RefreshCw :size="14"/>刷新</button></div>
    <div v-if="!list.length" class="empty-state">暂无报告。保存餐食后，可以生成近 7 天或近 30 天的营养分析。</div>
    <button v-for="item in list" :key="item.id" class="report-list-item" @click="open(item.id)">
      <FileText :size="19"/><span><b>{{item.days}} 日营养报告</b><small>{{formatDate(item.created_at)}} · {{item.source==='demo'?'演示':'BiSheng'}}</small></span><span class="report-list-arrow">›</span>
    </button>
  </section>
</template>
