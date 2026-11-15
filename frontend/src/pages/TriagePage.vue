<script setup lang="ts">
import { ref } from 'vue'
import { api, jsonBody } from '../lib/api'
type Message = {role:'user'|'assistant',content:string}
const messages=ref<Message[]>([]), input=ref(''), busy=ref(false), error=ref('')
async function send(){
  const value=input.value.trim()
  if(!value || busy.value)return
  const next:Message[]=[...messages.value,{role:'user',content:value}]
  busy.value=true; error.value=''
  try{
    const result=await api<{reply:string}>('/triage',{method:'POST',body:jsonBody({messages:next.slice(-20)})})
    messages.value=[...next,{role:'assistant',content:result.reply}]; input.value=''
  }catch(e){error.value=e instanceof Error?e.message:'服务暂不可用'}
  finally{busy.value=false}
}
</script>
<template>
  <section class="page triage-page">
    <h1 class="page-title">症状导诊</h1>
    <p class="page-subtitle">说说哪里不舒服，我会先问几个问题，再提供科室参考。内容会发送至模型服务，对话在离开页面后清空。</p>
    <p class="triage-warning">如有持续胸痛、严重呼吸困难、意识障碍或大出血，请立即拨打 120 或前往急诊。此服务不能诊断疾病。</p>
    <div aria-live="polite" class="triage-messages"><p v-if="!messages.length">请描述主要症状、持续时间和严重程度。</p><div v-for="(item,i) in messages" :key="i" class="triage-message"><strong>{{item.role==='user'?'我':'导诊助手'}}</strong><p>{{item.content}}</p></div></div>
    <p v-if="error" role="alert">{{error}}</p>
    <form @submit.prevent="send"><label for="triage-input">描述症状</label><textarea id="triage-input" v-model="input" maxlength="1500" rows="3" placeholder="例如：头痛两天，伴有发热"></textarea><button type="submit" :disabled="busy || !input.trim()">{{busy?'正在思考…':'发送'}}</button><button type="button" :disabled="busy" @click="messages=[];input='';error=''">重新开始</button></form>
  </section>
</template>
<style scoped>
.triage-warning{padding:14px;background:#fff1e9;border-radius:12px;color:#8b3f21;line-height:1.6}.triage-messages{margin:20px 0}.triage-message{padding:12px;margin:10px 0;background:#f3f7f4;border-radius:12px;white-space:pre-wrap}.triage-message p{margin:6px 0}form{display:grid;gap:10px}textarea{width:100%;padding:12px;border:1px solid #aabbb1;border-radius:10px;font:inherit}form button{padding:12px;border:0;border-radius:10px;background:#22694f;color:white}form button:disabled{opacity:.5}
</style>
