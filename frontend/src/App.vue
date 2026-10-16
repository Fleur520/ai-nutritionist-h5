<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { House, Camera, MessageCircle, ClipboardList, UserRound, Sparkles, Leaf } from 'lucide-vue-next'
import { api } from './lib/api'
import { reportsEnabled } from './lib/features'
import AuthGate from './components/AuthGate.vue'
import HomePage from './pages/HomePage.vue'
import ScanPage from './pages/ScanPage.vue'
import ChatPage from './pages/ChatPage.vue'
import HistoryPage from './pages/HistoryPage.vue'
import ProfilePage from './pages/ProfilePage.vue'
import ReportPage from './pages/ReportPage.vue'
const tab=ref('home'),user=ref<{id:string,email:string}|null>(null),loading=ref(true)
const viewportHeight=ref(0),keyboardOpen=ref(false)
let largestViewport=0,lastViewportWidth=0
const tabs=[{id:'home',text:'首页',icon:House},{id:'scan',text:'拍照',icon:Camera},{id:'chat',text:'AI 咨询',icon:MessageCircle},{id:'history',text:'记录',icon:ClipboardList},{id:'profile',text:'我的',icon:UserRound}]
async function refresh(){try{user.value=await api('/auth/me')}catch{user.value=null}finally{loading.value=false}}
function measureViewport(){
  const height=window.visualViewport?.height||window.innerHeight
  const editing=document.activeElement?.matches('input,textarea')
  if(!editing||Math.abs(window.innerWidth-lastViewportWidth)>40)largestViewport=0
  lastViewportWidth=window.innerWidth
  largestViewport=Math.max(largestViewport,window.innerHeight,height)
  viewportHeight.value=Math.round(height)
  keyboardOpen.value=!!editing&&window.matchMedia('(pointer: coarse)').matches&&largestViewport-height>140
}
onMounted(()=>{
  void refresh();measureViewport()
  window.visualViewport?.addEventListener('resize',measureViewport)
  window.addEventListener('resize',measureViewport)
  window.addEventListener('focusin',measureViewport)
  window.addEventListener('focusout',measureViewport)
})
onBeforeUnmount(()=>{
  window.visualViewport?.removeEventListener('resize',measureViewport)
  window.removeEventListener('resize',measureViewport)
  window.removeEventListener('focusin',measureViewport)
  window.removeEventListener('focusout',measureViewport)
})
function go(value:string){tab.value=value;window.scrollTo({top:0,behavior:'instant'})}
</script>
<template>
  <div class="app-shell" :class="{'is-chat':!!user&&tab==='chat','keyboard-open':keyboardOpen,'is-auth':!user}" :style="viewportHeight?{'--app-height':viewportHeight+'px'}:{}">
    <div v-if="loading" class="center-loader" role="status"><Sparkles :size="28"/><span>正在准备你的营养空间…</span></div>
    <AuthGate v-else-if="!user" @authenticated="refresh" />
    <template v-else>
      <header class="app-header"><button class="brand" aria-label="食光首页" @click="go('home')"><span class="brand-mark"><Sparkles :size="21"/></span><span class="brand-copy"><strong>食光</strong><span>AI NUTRITION</span></span></button><div class="header-tip"><Leaf :size="13"/> 好好吃饭，慢慢变好</div></header>
      <main class="view-body" id="main-content">
        <HomePage v-if="tab==='home'" @go="go"/>
        <ScanPage v-else-if="tab==='scan'" @go="go"/>
        <ChatPage v-else-if="tab==='chat'"/>
        <HistoryPage v-else-if="tab==='history'" @go="go"/>
        <ReportPage v-else-if="reportsEnabled && tab==='report'" @go="go"/>
        <ProfilePage v-else @logout="user=null;tab='home'"/>
      </main>
      <nav class="tabbar" aria-label="底部导航">
        <button v-for="item in tabs" :key="item.id" type="button" class="tab" :class="{selected:tab===item.id}" :aria-current="tab===item.id?'page':undefined" @click="go(item.id)">
          <span class="tab-icon"><component :is="item.icon" :size="21" :stroke-width="tab===item.id?2.6:1.85"/></span><span>{{item.text}}</span>
        </button>
      </nav>
    </template>
  </div>
</template>
