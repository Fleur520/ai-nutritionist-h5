<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { ArrowDown, ArrowUpRight, Check, Copy, LoaderCircle, RotateCcw, Send, ShieldCheck, Sparkles, Square } from 'lucide-vue-next'
import { api, streamMessage } from '../lib/api'
import MarkdownContent from '../components/MarkdownContent.vue'

type ReplyState = 'streaming' | 'complete' | 'stopped' | 'failed'
interface ChatMessage { id: number; role: 'user' | 'assistant'; content: string; state?: ReplyState }
function makeThreadId() {
  const bytes = new Uint8Array(16)
  if (typeof globalThis.crypto?.getRandomValues === 'function') globalThis.crypto.getRandomValues(bytes)
  else for (let i = 0; i < 16; i++) bytes[i] = Math.floor(Math.random() * 256)
  return Array.from(bytes).map(value => value.toString(16).padStart(2, '0')).join('')
}
const threadId = localStorage.getItem('nutrition_thread') || makeThreadId()
localStorage.setItem('nutrition_thread', threadId)
const messages = ref<ChatMessage[]>([])
const draft = ref(''), busy = ref(false), historyLoading = ref(true), historyError = ref(false), error = ref('')
const viewport = ref<HTMLElement | null>(null), composer = ref<HTMLTextAreaElement | null>(null)
const nearBottom = ref(true), copiedId = ref<number | null>(null)
let nextId = 0, disposed = false
let request: AbortController | null = null
let copyTimeout: ReturnType<typeof setTimeout> | undefined
const presets = [
  { label: '早餐怎么吃', question: '早餐怎么搭配更合理？', emoji: '🥑' },
  { label: '轻松管理体重', question: '想管理体重，一日三餐怎么搭配？', emoji: '🥗' },
  { label: '外卖也能吃得好', question: '经常吃外卖，怎么吃得更均衡？', emoji: '🍱' },
]
function updateScrollPosition() {
  const element = viewport.value
  if (element) nearBottom.value = element.scrollHeight - element.scrollTop - element.clientHeight < 96
}
async function scrollToBottom(force = false) {
  if (!force && !nearBottom.value) return
  await nextTick()
  if (disposed || (!force && !nearBottom.value)) return
  const element = viewport.value
  if (element) { element.scrollTop = element.scrollHeight; nearBottom.value = true }
}
async function loadHistory() {
  historyLoading.value = true
  historyError.value = false
  try {
    const history = await api<{ role: string; content: string }[]>('/chat/history?thread_id=' + encodeURIComponent(threadId))
    if (disposed) return
    messages.value = history.filter(message => (message.role === 'user' || message.role === 'assistant') && typeof message.content === 'string' && message.content.trim())
      .map(message => ({ id: ++nextId, role: message.role as ChatMessage['role'], content: message.content, state: 'complete' }))
    await scrollToBottom(true)
  } catch { if (!disposed) historyError.value = true }
  finally { if (!disposed) historyLoading.value = false }
}
function resizeComposer() {
  const element = composer.value
  if (!element) return
  element.style.height = 'auto'
  element.style.height = Math.min(element.scrollHeight, 120) + 'px'
}
async function send(input?: string) {
  const question = (input || draft.value).trim()
  if (!question || busy.value || historyLoading.value || historyError.value) return
  busy.value = true; draft.value = ''; error.value = ''; request = new AbortController()
  messages.value.push({ id: ++nextId, role: 'user', content: question })
  messages.value.push({ id: ++nextId, role: 'assistant', content: '', state: 'streaming' })
  const replyIndex = messages.value.length - 1
  await nextTick(); resizeComposer(); await scrollToBottom(true)
  try {
    await streamMessage(question, threadId, text => {
      if (disposed) return
      messages.value[replyIndex].content += text
      void scrollToBottom()
    }, request.signal)
    if (!messages.value[replyIndex].content.trim()) throw new Error('暂时没有收到有效回复，请重试。')
    messages.value[replyIndex].state = 'complete'
  } catch (cause) {
    if (disposed) return
    if (request?.signal.aborted) messages.value[replyIndex].state = 'stopped'
    else { messages.value[replyIndex].state = 'failed'; error.value = cause instanceof Error ? cause.message : '回复暂时中断了，请稍后重试。' }
  } finally {
    request = null
    if (!disposed) { busy.value = false; void scrollToBottom() }
  }
}
function retryLastReply() {
  const last = messages.value.at(-1), question = messages.value.at(-2)
  if (busy.value || last?.role !== 'assistant' || question?.role !== 'user') return
  messages.value.splice(-2)
  void send(question.content)
}
function handleComposerKey(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && window.matchMedia('(pointer: fine)').matches) {
    event.preventDefault()
    if (!busy.value) void send()
  }
}
async function copyReply(message: ChatMessage) {
  try {
    if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(message.content)
    else {
      // The LAN deployment uses HTTP, where the Clipboard API is unavailable.
      const previousFocus = document.activeElement as HTMLElement | null
      const copyField = document.createElement('textarea')
      copyField.value = message.content
      copyField.readOnly = true
      copyField.style.cssText = 'position:fixed;left:-9999px;top:0;opacity:0;font-size:16px'
      document.body.appendChild(copyField)
      try {
        copyField.select()
        if (!document.execCommand('copy')) throw new Error('clipboard unavailable')
      } finally { copyField.remove(); previousFocus?.focus({ preventScroll: true }) }
    }
    copiedId.value = message.id
    if (copyTimeout) clearTimeout(copyTimeout)
    copyTimeout = setTimeout(() => { copiedId.value = null }, 2000)
  } catch { error.value = '当前浏览器暂不支持复制，请长按回复选择文字。' }
}
onMounted(loadHistory)
onBeforeUnmount(() => { disposed = true; request?.abort(); if (copyTimeout) clearTimeout(copyTimeout) })
</script>

<template>
  <section class="conversation-screen" aria-label="AI 营养咨询">
    <header class="conversation-header">
      <div class="conversation-avatar"><Sparkles :size="23" :stroke-width="1.8" /></div>
      <div><h1>你的 AI 营养师</h1><p><span class="conversation-online"></span>从一餐开始，陪你吃得更好</p></div>
      <span class="conversation-badge">食光 AI</span>
    </header>
    <div class="conversation-body-wrap">
      <div ref="viewport" class="conversation-messages" tabindex="0" aria-label="聊天记录" @scroll.passive="updateScrollPosition">
        <div v-if="historyLoading" class="conversation-loading" role="status"><LoaderCircle :size="20" class="spinning" />正在整理对话…</div>
        <div v-else-if="historyError" class="conversation-history-error"><p>暂时没能加载对话，请检查网络后重试。</p><button type="button" @click="loadHistory"><RotateCcw :size="16" />重新加载</button></div>
        <div v-else-if="!messages.length" class="conversation-welcome">
          <div class="conversation-welcome-art" aria-hidden="true"><span>🌿</span><i>✦</i></div>
          <span class="conversation-eyebrow">A LITTLE BETTER, EVERY MEAL</span>
          <h2>好好吃饭，也是一种照顾</h2><p>关于三餐搭配、饮食习惯的小困惑，<br />都可以在这里聊聊。</p>
          <div class="conversation-preset-label">试着问我</div>
          <button v-for="preset in presets" :key="preset.label" class="conversation-preset" type="button" @click="send(preset.question)"><span class="conversation-preset-emoji" aria-hidden="true">{{ preset.emoji }}</span><span>{{ preset.label }}</span><ArrowUpRight :size="18" /></button>
        </div>
        <article v-for="(message, index) in messages" :key="message.id" class="conversation-message" :class="`is-${message.role}`">
          <div v-if="message.role === 'assistant'" class="conversation-message-label"><Sparkles :size="13" />食光 AI<span v-if="message.state === 'streaming'">正在回复</span></div>
          <div v-if="message.role === 'user'" class="conversation-user-bubble">{{ message.content }}</div>
          <div v-else class="conversation-assistant-card" :aria-busy="message.state === 'streaming'">
            <MarkdownContent v-if="message.content" :content="message.content" />
            <div v-else-if="message.state === 'streaming'" class="conversation-thinking" role="status"><span></span><span></span><span></span><small>正在想一份适合你的建议</small></div>
            <p v-else class="conversation-empty-reply">{{ message.state === 'stopped' ? '已停止回答，想聊什么可以继续问我。' : '暂时没有收到回复，请再试一次。' }}</p>
            <div v-if="message.state === 'failed' || message.state === 'stopped'" class="conversation-reply-status">{{ message.state === 'failed' && message.content ? '回复中断，以上内容可能不完整' : message.state === 'stopped' ? '回答已停止' : '回复未完成' }}</div>
          </div>
          <div v-if="message.role === 'assistant' && message.state !== 'streaming'" class="conversation-message-tools">
            <button v-if="message.content" type="button" :aria-label="copiedId === message.id ? '已复制回复' : '复制回复'" @click="copyReply(message)"><Check v-if="copiedId === message.id" :size="14" /><Copy v-else :size="14" /><span>{{ copiedId === message.id ? '已复制' : '复制' }}</span></button>
            <button v-if="index === messages.length - 1 && (message.state === 'failed' || message.state === 'stopped')" type="button" :disabled="busy" @click="retryLastReply"><RotateCcw :size="14" />重新回答</button>
          </div>
        </article>
      </div>
      <button v-if="!nearBottom && messages.length" class="conversation-jump" type="button" aria-label="回到最新消息" @click="scrollToBottom(true)"><ArrowDown :size="16" />最新消息</button>
    </div>
    <div class="conversation-composer">
      <div v-if="error" class="conversation-error" role="alert">{{ error }}<button type="button" aria-label="关闭提示" @click="error = ''">×</button></div>
      <form class="conversation-compose-form" @submit.prevent="send()">
        <textarea ref="composer" v-model="draft" rows="1" maxlength="1500" aria-label="输入营养问题" placeholder="今天想怎么吃？问问食光…" :disabled="historyLoading || historyError" @input="resizeComposer" @keydown="handleComposerKey"></textarea>
        <button v-if="busy" class="conversation-send is-stop" type="button" aria-label="停止回答" @pointerdown.prevent @click="request?.abort()"><Square :size="16" fill="currentColor" /></button>
        <button v-else class="conversation-send" type="submit" :disabled="!draft.trim() || historyLoading || historyError" aria-label="发送消息" @pointerdown.prevent><Send :size="19" /></button>
      </form>
      <p class="conversation-safety"><ShieldCheck :size="12" />AI 建议仅供日常饮食参考</p>
    </div>
  </section>
</template>

<style scoped>
.conversation-screen{display:flex;flex:1;flex-direction:column;min-width:0;min-height:0;height:100%;background:#f8f8f1;overflow:hidden}
.conversation-header{flex-shrink:0;display:flex;align-items:center;gap:11px;padding:12px 20px 14px;border-bottom:1px solid #e9ede3;background:#fffef9}
.conversation-avatar{display:grid;place-items:center;flex-shrink:0;width:44px;height:44px;border:1px solid #dfebde;border-radius:16px;background:#ecf3e7;color:#3c7854}
.conversation-header h1{margin:0 0 5px;color:#244b38;font-size:17px;font-weight:750;letter-spacing:-.4px}.conversation-header p{display:flex;align-items:center;gap:5px;margin:0;font-size:11px;color:#839581}.conversation-online{width:5px;height:5px;border-radius:50%;background:#71a97d}.conversation-badge{margin-left:auto;white-space:nowrap;font-size:9px;letter-spacing:1px;border:1px solid #e5ebdc;color:#83947c;border-radius:20px;padding:5px 7px}
.conversation-body-wrap{position:relative;display:flex;flex:1;min-height:0;min-width:0}.conversation-messages{flex:1;overflow-x:hidden;overflow-y:auto;min-width:0;padding:20px 16px 22px;overscroll-behavior-y:contain;scroll-padding:20px;-webkit-overflow-scrolling:touch}
.conversation-loading,.conversation-history-error{display:flex;align-items:center;justify-content:center;gap:8px;min-height:180px;font-size:13px;color:#829280}.conversation-history-error{flex-direction:column;text-align:center;line-height:1.7}.conversation-history-error p{margin:0}.conversation-history-error button{min-height:44px;padding:0 16px;border-radius:12px;background:#e8f0e2;color:#4a7154;display:flex;align-items:center;gap:6px}
.conversation-welcome{max-width:360px;margin:0 auto;text-align:center;padding:12px 5px 8px}.conversation-welcome-art{position:relative;width:74px;height:74px;display:grid;place-items:center;margin:0 auto 20px;background:#eaf0df;border-radius:26px 26px 30px 15px;transform:rotate(-7deg)}.conversation-welcome-art span{font-size:39px;transform:rotate(7deg)}.conversation-welcome-art i{position:absolute;right:-8px;top:-10px;color:#d79d71;font-style:normal;font-size:26px}.conversation-eyebrow{color:#9baf92;font-size:8px;letter-spacing:1.9px;font-weight:650}.conversation-welcome h2{margin:12px 0 10px;color:#294c39;font-size:21px;letter-spacing:-.6px;font-weight:750}.conversation-welcome > p{font-size:13px;line-height:1.85;color:#8c9986;margin:0 0 23px}.conversation-preset-label{font-size:10px;color:#a0ab98;margin:0 0 9px;text-align:left;letter-spacing:1px}.conversation-preset{display:flex;align-items:center;gap:10px;width:100%;min-height:53px;text-align:left;background:#fffefb;border:1px solid #e6eade;border-radius:15px;padding:10px 13px;margin:0 0 9px;color:#4a674c;font-size:13px}.conversation-preset-emoji{font-size:20px;width:29px}.conversation-preset > svg{margin-left:auto;color:#a0b295}
.conversation-message{margin:0 0 23px;min-width:0}.conversation-message.is-user{display:flex;justify-content:flex-end}.conversation-message-label{display:flex;align-items:center;gap:5px;color:#83937a;font-size:10px;font-weight:600;margin:0 0 8px 2px}.conversation-message-label > span{color:#b2b9a9;font-weight:400;margin-left:6px}.conversation-user-bubble{max-width:87%;padding:12px 16px;font-size:15px;line-height:1.75;white-space:pre-wrap;overflow-wrap:anywhere;color:#fff;background:#2f634b;border-radius:18px 18px 5px 18px;box-shadow:0 4px 8px #315c3810}.conversation-assistant-card{width:100%;padding:18px 16px;background:#fffefa;border:1px solid #e9ebdf;border-radius:6px 18px 18px 18px;color:#405242;box-shadow:0 3px 10px #4d5d3310}
.conversation-thinking{min-height:30px;display:flex;align-items:center;gap:4px;color:#7b9776}.conversation-thinking > span{width:5px;height:5px;background:#9cb88c;border-radius:50%;animation:thought 1.1s ease-in-out infinite}.conversation-thinking > span:nth-child(2){animation-delay:.15s}.conversation-thinking > span:nth-child(3){animation-delay:.3s}.conversation-thinking small{font-size:12px;margin-left:7px;color:#90a087}.conversation-empty-reply{margin:0;line-height:1.8;font-size:14px;color:#82917d}.conversation-reply-status{font-size:10px;color:#a58d6c;padding-top:12px;margin-top:12px;border-top:1px solid #f0eee2}.conversation-message-tools{display:flex;gap:10px;padding:4px 3px 0}.conversation-message-tools button{display:inline-flex;align-items:center;justify-content:center;gap:5px;min-width:44px;min-height:36px;padding:4px;font-size:10px;color:#93a08a;background:none}
.conversation-jump{position:absolute;z-index:2;bottom:12px;left:50%;transform:translateX(-50%);display:flex;align-items:center;justify-content:center;gap:6px;min-height:38px;padding:8px 14px;border:1px solid #e2e9d9;border-radius:22px;background:#fffef6;box-shadow:0 4px 18px #345a3520;color:#4b7453;font-size:11px;white-space:nowrap}
.conversation-composer{flex-shrink:0;padding:10px 14px 5px;background:#fffef9;border-top:1px solid #e9ede3}.conversation-compose-form{display:flex;gap:7px;align-items:flex-end;padding:7px;border:1px solid #dce5d4;border-radius:19px;background:#f7f9f1;transition:border-color .2s}.conversation-compose-form:focus-within{border-color:#a9bea1}.conversation-compose-form textarea{display:block;flex:1;width:100%;min-width:0;min-height:40px;max-height:120px;padding:9px 7px;resize:none;overflow-y:auto;background:transparent;border:0;outline:0;box-shadow:none;color:#344f3c;font:inherit;font-size:16px;line-height:22px}.conversation-compose-form textarea::placeholder{color:#a0aa95;font-size:13px}.conversation-send{display:grid;place-items:center;flex-shrink:0;width:42px;height:42px;border-radius:14px;background:#2f684c;color:#fff}.conversation-send:disabled{opacity:1;background:#dce6d3;color:#9cb18f}.conversation-send.is-stop{color:#56774d;background:#e1ecd6}.conversation-safety{display:flex;justify-content:center;align-items:center;gap:4px;margin:7px 0 1px;color:#a7ae9c;font-size:9px}.conversation-error{display:flex;align-items:center;gap:8px;padding:8px 10px;margin-bottom:8px;border-radius:10px;background:#fff0e6;color:#a37557;font-size:12px;line-height:1.6}.conversation-error button{margin-left:auto;min-width:32px;min-height:32px;font-size:21px;color:#ae937b;background:transparent}
@keyframes thought{0%,70%,100%{opacity:.35;transform:translateY(0)}35%{opacity:1;transform:translateY(-3px)}}
@media(max-width:359px){.conversation-header{padding-right:15px;padding-left:15px}.conversation-badge{display:none}.conversation-messages{padding:15px 11px 18px}.conversation-assistant-card{padding:16px 13px}.conversation-welcome h2{font-size:19px}.conversation-welcome-art{width:62px;height:62px;margin-bottom:14px}}
@media(max-height:680px){.conversation-welcome{padding-top:1px}.conversation-welcome-art{width:56px;height:56px;margin-bottom:12px}.conversation-welcome-art span{font-size:32px}.conversation-welcome > p{margin-bottom:16px}.conversation-header{padding-top:8px;padding-bottom:10px}}
@media(prefers-reduced-motion:reduce){.conversation-thinking > span{animation:none}.conversation-compose-form{transition:none}}
</style>
