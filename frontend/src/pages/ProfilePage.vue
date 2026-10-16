<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { UserRound, Save, LogOut, ShieldCheck, CheckCircle2, RefreshCw } from 'lucide-vue-next'
import { api, jsonBody, type Profile } from '../lib/api'

const emit = defineEmits<{ logout: [] }>()
const model = ref<Profile>({ user_id: '', name: '', age: null, height_cm: null, weight_kg: null, goal: 'balanced' })
const busy = ref(false), loading = ref(true), loggingOut = ref(false), loaded = ref(false), message = ref(''), loadError = ref(''), success = ref(false)
async function load() {
  loading.value = true
  loadError.value = ''
  try { model.value = await api<Profile>('/profile'); loaded.value = true }
  catch (failure) { loadError.value = failure instanceof Error ? failure.message : '个人档案暂时无法加载' }
  finally { loading.value = false }
}
onMounted(load)
function optionalNumber(value: unknown) {
  return value === '' || value === null || value === undefined ? null : Number(value)
}
async function save() {
  if (busy.value || !loaded.value) return
  busy.value = true; message.value = ''; success.value = false
  try {
    const payload = { name: model.value.name, goal: model.value.goal, age: optionalNumber(model.value.age), height_cm: optionalNumber(model.value.height_cm), weight_kg: optionalNumber(model.value.weight_kg) }
    await api('/profile', { method: 'PUT', body: jsonBody(payload) })
    message.value = '档案已保存，下次聊饮食时更懂你。'; success.value = true
  } catch (failure) { message.value = failure instanceof Error ? failure.message : '保存失败，请稍后重试' }
  finally { busy.value = false }
}
async function logout() {
  loggingOut.value = true; message.value = ''; success.value = false
  try { await api('/auth/logout', { method: 'POST' }); emit('logout') }
  catch (failure) { message.value = failure instanceof Error ? failure.message : '退出失败，请稍后重试' }
  finally { loggingOut.value = false }
}
</script>

<template>
  <section class="page profile-page">
    <header class="page-header"><div class="eyebrow">A LITTLE ABOUT YOU</div><h1 class="page-title">让建议，更懂你。</h1><p class="page-subtitle">一点关于你的信息，帮助我们把饮食建议说得更贴心。</p></header>
    <div class="profile-hero"><div class="profile-icon"><UserRound :size="26" /></div><div><strong>我的营养档案</strong><p>按自己的节奏，慢慢完善就好</p></div></div>
    <div v-if="loadError" class="profile-load-error" role="alert"><p>{{ loadError }}</p><button type="button" class="text-action" @click="load"><RefreshCw :size="16" />重新加载档案</button></div>
    <form @submit.prevent="save" class="profile-form">
      <fieldset :disabled="loading || busy || !loaded">
        <div class="form-section-heading"><h2>基本信息</h2><span>{{ loading ? '正在加载…' : '年龄、身高与体重可选填' }}</span></div>
        <label class="form-label">昵称<input v-model="model.name" maxlength="60" autocomplete="nickname" placeholder="怎么称呼你？" /></label>
        <div class="form-grid"><label class="form-label">年龄<input type="number" v-model.number="model.age" min="18" max="110" step="1" inputmode="numeric" placeholder="18 岁及以上" /></label><label class="form-label">身高（厘米）<input type="number" v-model.number="model.height_cm" min="100" max="240" step="0.1" inputmode="decimal" placeholder="例如 165" /></label></div>
        <label class="form-label">体重（千克）<input type="number" v-model.number="model.weight_kg" min="20" max="350" step="0.1" inputmode="decimal" placeholder="例如 55" /></label>
        <label class="form-label">我想要<select v-model="model.goal"><option value="balanced">吃得均衡，保持好状态</option><option value="lose">管理体重，轻盈一点</option><option value="gain">增肌与补充营养</option></select></label>
        <p v-if="message" :class="success ? 'notice success' : 'error'" :role="success ? 'status' : 'alert'"><CheckCircle2 v-if="success" :size="18" />{{ message }}</p>
        <button class="primary-button" type="submit" :disabled="busy || loading || !loaded"><Save :size="18" />{{ busy ? '正在保存…' : '保存我的档案' }}</button>
      </fieldset>
    </form>
    <div class="privacy-note"><ShieldCheck :size="19" /><p>你的照片、饮食日记和个人档案仅供自己的账号查看。你可以随时回来更新这些信息。</p></div>
    <button class="logout-button" type="button" :disabled="loggingOut" @click="logout"><LogOut :size="17" />{{ loggingOut ? '正在退出…' : '退出登录' }}</button>
  </section>
</template>

<style scoped>
.profile-form{background:#fff;border:1px solid #e5ebe5;border-radius:22px;padding:20px}.profile-form fieldset{border:0;margin:0;padding:0;min-width:0}.form-section-heading{display:flex;flex-direction:column;gap:6px;margin-bottom:22px}.form-section-heading h2{font-size:17px;margin:0;color:#254e38}.form-section-heading span{font-size:12px;color:#829286}.profile-form .form-label{font-size:14px}.profile-hero p{line-height:1.6}.profile-load-error{background:#fff3ed;border:1px solid #f5dbca;border-radius:16px;padding:16px;margin-bottom:18px;color:#935d43}.profile-load-error p{font-size:14px;line-height:1.6;margin:0 0 5px}.profile-load-error button{min-height:44px;padding:0}.notice.success{color:#245b43;background:#edf6ed;font-size:14px;align-items:flex-start}.notice.success svg{flex-shrink:0;margin-top:2px}.privacy-note{padding:18px 16px}.privacy-note p{font-size:13px;color:#75877b}.logout-button{min-height:48px;font-size:14px;padding:10px 16px}.profile-form .error{margin-top:0}
</style>
