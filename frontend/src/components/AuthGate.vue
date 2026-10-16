<script setup lang="ts">
import { ref } from 'vue'
import { api, jsonBody } from '../lib/api'
import { Sparkles, ArrowRight, Eye, EyeOff, Camera, MessageCircle, BookOpen } from 'lucide-vue-next'
const emit = defineEmits<{ authenticated: [] }>()
const register = ref(false), email = ref(''), password = ref(''), busy = ref(false), error = ref(''), showPassword = ref(false)
async function submit() {
  if (busy.value) return
  busy.value = true; error.value = ''
  try { await api('/auth/' + (register.value ? 'register' : 'login'), { method: 'POST', body: jsonBody({ email: email.value, password: password.value }) }); emit('authenticated') }
  catch (failure) { error.value = failure instanceof Error ? failure.message : '登录失败，请稍后再试' }
  finally { busy.value = false }
}
function switchMode() { register.value = !register.value; error.value = ''; showPassword.value = false }
</script>

<template>
  <section class="auth-screen">
    <div class="auth-art">
      <div class="auth-wordmark"><div class="auth-art-badge"><Sparkles :size="23" /></div><span><strong>食光</strong><small>AI NUTRITION</small></span></div>
      <div class="auth-big">吃好每一餐，<br />照顾好自己<span class="auth-peach-dot">。</span></div>
      <p>把好好吃饭，变成一件轻松的小事。</p>
      <div class="auth-abstract" aria-hidden="true"><div class="orb orb-one"></div><div class="orb orb-two"></div><div class="orb orb-three"></div></div>
    </div>
    <form class="auth-form" @submit.prevent="submit" :aria-busy="busy">
      <div class="eyebrow">{{ register ? 'YOUR NEW CHAPTER' : 'WELCOME BACK' }}</div>
      <h1>{{ register ? '开启你的食光' : '欢迎回来' }}</h1>
      <p class="muted">{{ register ? '从今天起，慢慢养成适合自己的饮食习惯。' : '今天也要好好吃饭，照顾好自己。' }}</p>
      <label class="form-label">邮箱<input type="email" autocomplete="username" inputmode="email" autocapitalize="off" spellcheck="false" v-model.trim="email" placeholder="输入你的邮箱" maxlength="254" :disabled="busy" required /></label>
      <label class="form-label">密码<span class="auth-password"><input :type="showPassword ? 'text' : 'password'" :autocomplete="register ? 'new-password' : 'current-password'" v-model="password" minlength="8" maxlength="128" placeholder="至少 8 位密码" :disabled="busy" required /><button type="button" :aria-label="showPassword ? '隐藏密码' : '显示密码'" :aria-pressed="showPassword" @click="showPassword = !showPassword"><EyeOff v-if="showPassword" :size="19" /><Eye v-else :size="19" /></button></span></label>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <button class="primary-button" :disabled="busy" type="submit">{{ busy ? '正在进入…' : register ? '创建账号，开始记录' : '登录我的营养空间' }}<ArrowRight :size="18" /></button>
      <p class="auth-switch">{{ register ? '已经有账号了？' : '第一次来到食光？' }}<button type="button" :disabled="busy" @click="switchMode">{{ register ? '立即登录' : '创建新账号' }}</button></p>
      <div class="auth-benefits" aria-label="食光功能"><span><Camera :size="16" />拍照记餐</span><span><MessageCircle :size="16" />AI 饮食建议</span><span><BookOpen :size="16" />饮食日记</span></div>
      <p class="microcopy">陪伴你的日常饮食，提供一般健康信息。<br />如有疾病或特殊营养需求，请咨询专业人士。</p>
    </form>
  </section>
</template>

<style scoped>
.auth-wordmark{position:relative;z-index:1;display:flex;align-items:center;gap:11px;margin-bottom:24px}.auth-wordmark .auth-art-badge{margin:0;width:44px;height:44px;border-radius:15px;background:#ffffff24}.auth-wordmark strong{font-size:24px;letter-spacing:2px;display:block;line-height:1.2}.auth-wordmark small{display:block;font-size:9px;letter-spacing:2px;color:#cfdfd3;margin-top:4px}.auth-peach-dot{color:#eec6a7}.auth-form .muted{font-size:14px;line-height:1.7;margin-bottom:25px}.auth-password{position:relative;display:block;margin-top:8px}.auth-password input{padding-right:50px;margin-top:0}.auth-password button{position:absolute;right:3px;top:50%;transform:translateY(-50%);background:transparent;width:44px;height:44px;display:grid;place-items:center;color:#839789;border-radius:10px}.auth-switch{display:flex;justify-content:center;align-items:center;gap:2px;font-size:13px}.auth-switch button{min-height:44px;padding:8px 7px;font-size:14px}.auth-benefits{display:flex;align-items:center;justify-content:center;gap:17px;border-top:1px solid #e9eee6;padding-top:22px;margin-top:4px;flex-wrap:wrap}.auth-benefits span{display:inline-flex;gap:6px;align-items:center;color:#829387;font-size:11px;white-space:nowrap}.auth-form .microcopy{font-size:11px;color:#96a198;line-height:1.8;margin:20px 0 0}.auth-art p{font-size:14px;line-height:1.7;max-width:260px}
@media(max-width:360px){.auth-benefits{gap:11px}.auth-benefits span{font-size:10px}.auth-form{padding-inline:22px}.auth-big{font-size:28px}}
</style>
