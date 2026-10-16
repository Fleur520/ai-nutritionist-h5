<script setup lang="ts">
import { nextTick, onMounted, ref } from 'vue'
import { MessageCircle, Send, Sparkles, ShieldCheck } from 'lucide-vue-next'
import { api, streamMessage } from '../lib/api'
function makeThreadId() {
  // crypto.randomUUID is only available in secure contexts (HTTPS / localhost).
  // crypto.getRandomValues remains available on ordinary LAN HTTP pages.
  const bytes = new Uint8Array(16)
  if (typeof globalThis.crypto?.getRandomValues === 'function') crypto.getRandomValues(bytes)
  else for (let i=0;i<16;i++) bytes[i] = Math.floor(Math.random()*256)
  return Array.from(bytes).map(x=>x.toString(16).padStart(2,'0')).join('')
}
const threadId=localStorage.getItem('nutrition_thread')||makeThreadId()
localStorage.setItem('nutrition_thread',threadId)
const messages=ref<{role:string;content:string}[]>([]),draft=ref(''),busy=ref(false),error=ref(''),viewport=ref<HTMLElement|null>(null)
const presets=['早餐怎么搭配更合理？','减脂期间怎么补充蛋白质？','怎么改善经常吃外卖的问题？']
onMounted(async()=>{messages.value=await api<{role:string;content:string}[]>('/chat/history?thread_id='+encodeURIComponent(threadId)).catch(()=>[])})
async function scroll(){await nextTick();viewport.value?.scrollTo({top:viewport.value.scrollHeight,behavior:'smooth'})}
async function send(input?:string){const q=(input||draft.value).trim();if(!q||busy.value)return;busy.value=true;draft.value='';error.value='';messages.value.push({role:'user',content:q});messages.value.push({role:'assistant',content:''});const replyIndex=messages.value.length-1;await scroll()
try{await streamMessage(q,threadId,s=>{messages.value[replyIndex].content+=s;void scroll()})}catch(e){error.value=e instanceof Error?e.message:'咨询中断';if(!messages.value[replyIndex]?.content)messages.value.pop()}finally{busy.value=false;await scroll()}}
</script>
<template><section class="chat-screen"><div class="chat-intro"><div class="chat-avatar"><Sparkles :size="24"/></div><div><h1>AI 营养师</h1><p><span class="online-dot"></span> 在线 · 营养知识与生活方式建议</p></div></div>
<div ref="viewport" class="chat-messages"><div v-if="!messages.length" class="chat-welcome"><div class="welcome-emoji">🌱</div><h2>你好，有什么想聊的？</h2><p>从今天的一餐开始，让健康饮食变得简单一点。</p><button v-for="p in presets" :key="p" @click="send(p)">{{p}} <span>↗</span></button></div>
<div v-for="(m,index) in messages" :key="index" class="chat-bubble" :class="m.role"><div class="bubble-role">{{m.role==='assistant'?'食光 AI':'我'}}</div><div class="bubble-content">{{m.content||'思考中…'}}</div></div></div>
<div v-if="error" class="chat-error">{{error}}</div>
<div class="chat-composer"><form @submit.prevent="send()"><input v-model="draft" :disabled="busy" maxlength="1500" placeholder="问问关于饮食、营养的问题…"/><button :disabled="busy||!draft.trim()" type="submit" aria-label="发送消息"><Send :size="18"/></button></form><div class="chat-safety"><ShieldCheck :size="12"/> 仅供日常健康参考，不替代医生建议</div></div></section></template>
