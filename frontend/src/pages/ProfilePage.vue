<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { UserRound, Save, LogOut, ShieldCheck } from 'lucide-vue-next'
import { api, jsonBody, type Profile } from '../lib/api'
const emit=defineEmits<{logout:[]}>(),model=ref<Profile>({user_id:'',name:'',age:null,height_cm:null,weight_kg:null,goal:'balanced'}),busy=ref(false),message=ref('')
onMounted(async()=>{model.value=await api<Profile>('/profile').catch(()=>model.value)})
async function save(){busy.value=true;message.value='';try{await api('/profile',{method:'PUT',body:jsonBody(model.value)});message.value='保存成功'}catch(e){message.value=e instanceof Error?e.message:'保存失败'}finally{busy.value=false}}
async function logout(){await api('/auth/logout',{method:'POST'});emit('logout')}
</script>
<template><section class="page profile-page"><div class="eyebrow">A LITTLE ABOUT YOU</div><h1 class="page-title">让建议，更懂你。</h1><p class="page-subtitle">填写基本资料，AI 可以结合你的目标给出更合适的一般性建议。</p>
<div class="profile-hero"><div class="profile-icon"><UserRound :size="26"/></div><div><strong>我的营养档案</strong><p>信息仅用于你的健康管理体验</p></div></div>
<form @submit.prevent="save" class="profile-form"><label class="form-label">昵称<input v-model="model.name" maxlength="60" placeholder="怎么称呼你？"/></label><div class="form-grid"><label class="form-label">年龄（18+）<input type="number" v-model.number="model.age" min="18" max="110"/></label><label class="form-label">身高（cm）<input type="number" v-model.number="model.height_cm" min="100" max="240" step="0.1"/></label></div><label class="form-label">体重（kg）<input type="number" v-model.number="model.weight_kg" min="20" max="350" step="0.1"/></label><label class="form-label">健康目标<select v-model="model.goal"><option value="balanced">均衡饮食</option><option value="lose">体重管理</option><option value="gain">增肌与补充营养</option></select></label><p v-if="message" class="notice">{{message}}</p><button class="primary-button" type="submit" :disabled="busy"><Save :size="17"/>{{busy?'保存中…':'保存我的档案'}}</button></form>
<div class="privacy-note"><ShieldCheck :size="18"/><p>照片及饮食记录关联个人账号，后端进行权限验证；正式对外服务请部署 HTTPS、备份和数据删除能力。</p></div><button class="logout-button" @click="logout"><LogOut :size="17"/>退出登录</button>
</section></template>
