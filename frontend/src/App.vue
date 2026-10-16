<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { House, Camera, MessageCircle, ClipboardList, UserRound, Sparkles } from 'lucide-vue-next'
import { api } from './lib/api'
import AuthGate from './components/AuthGate.vue'
import HomePage from './pages/HomePage.vue'
import ScanPage from './pages/ScanPage.vue'
import ChatPage from './pages/ChatPage.vue'
import HistoryPage from './pages/HistoryPage.vue'
import ProfilePage from './pages/ProfilePage.vue'
import ReportPage from './pages/ReportPage.vue'
const tab=ref('home'),user=ref<{id:string,email:string}|null>(null),loading=ref(true)
const tabs=[{id:'home',text:'首页',icon:House},{id:'scan',text:'拍照',icon:Camera},{id:'chat',text:'AI 咨询',icon:MessageCircle},{id:'history',text:'记录',icon:ClipboardList},{id:'profile',text:'我的',icon:UserRound}]
async function refresh(){try{user.value=await api('/auth/me')}catch{user.value=null}finally{loading.value=false}}
onMounted(refresh)
const go=(value:string)=>tab.value=value
</script>
<template>
  <div class="app-shell">
    <div v-if="loading" class="center-loader">食光 · 正在准备你的营养空间…</div>
    <AuthGate v-else-if="!user" @authenticated="refresh" />
    <template v-else>
      <header class="app-header"><div class="brand"><div class="brand-mark"><Sparkles :size="19"/></div><div><strong>食光</strong><span>AI Nutrition</span></div></div><div class="header-tip">把每一餐，吃得更明白 <span class="leaf">✳</span></div></header>
      <main class="view-body">
        <HomePage v-if="tab==='home'" @go="go"/>
        <ScanPage v-else-if="tab==='scan'" @go="go"/>
        <ChatPage v-else-if="tab==='chat'"/>
        <HistoryPage v-else-if="tab==='history'"/>
        <ReportPage v-else-if="tab==='report'" @go="go"/>
        <ProfilePage v-else @logout="user=null;tab='home'"/>
      </main>
      <nav class="tabbar" aria-label="底部导航">
        <button v-for="item in tabs" :key="item.id" type="button" class="tab" :class="{selected:tab===item.id}" @click="go(item.id)">
          <span class="tab-icon"><component :is="item.icon" :size="21" :stroke-width="tab===item.id?2.6:1.85"/></span><span>{{item.text}}</span>
        </button>
      </nav>
    </template>
  </div>
</template>
