<script setup lang="ts">
import { ref } from 'vue'
import { api, jsonBody } from '../lib/api'
import { Sparkles, ArrowRight } from 'lucide-vue-next'
const emit=defineEmits<{authenticated:[]}>()
const register=ref(false),email=ref(''),password=ref(''),busy=ref(false),error=ref('')
async function submit(){
 busy.value=true;error.value=''
 try {await api('/auth/'+(register.value?'register':'login'),{method:'POST',body:jsonBody({email:email.value,password:password.value})});emit('authenticated')}
 catch(e){error.value=e instanceof Error?e.message:'登录失败'}finally{busy.value=false}
}
</script>
<template>
 <section class="auth-screen"><div class="auth-art"><div class="auth-art-badge"><Sparkles :size="22"/></div><div class="auth-big">吃好每一餐，<br/>照顾好自己。</div><p>AI 营养建议 · 餐食拍照识别 · 健康饮食日记</p><div class="auth-abstract"><div class="orb orb-one"></div><div class="orb orb-two"></div><div class="orb orb-three"></div></div></div>
 <form class="auth-form" @submit.prevent="submit"><div class="eyebrow">WELCOME TO SHIGUANG</div><h1>{{register?'创建你的账户':'欢迎回来'}}</h1><p class="muted">专属于你的轻量 AI 营养助手</p>
 <label class="form-label">邮箱<input type="email" autocomplete="username" v-model.trim="email" placeholder="your@email.com" required/></label>
 <label class="form-label">密码<input type="password" :autocomplete="register?'new-password':'current-password'" v-model="password" minlength="8" placeholder="至少 8 位" required/></label>
 <p v-if="error" class="error">{{error}}</p><button class="primary-button" :disabled="busy" type="submit">{{busy?'请稍候…':register?'注册并开始':'进入我的营养空间'}}<ArrowRight :size="17"/></button>
 <p class="auth-switch">{{register?'已经有账号？':'还没有账号？'}} <button type="button" @click="register=!register;error=''">{{register?'立即登录':'创建新账户'}}</button></p>
 <p class="microcopy">本应用仅提供一般健康信息，不替代专业医疗诊断或治疗。</p></form></section>
</template>
